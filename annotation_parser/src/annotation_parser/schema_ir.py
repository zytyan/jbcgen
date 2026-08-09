from __future__ import annotations

import re
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
from enum import Enum

from .annotations import Annotation
from .clang_frontend import AstField, AstRecord, TranslationUnit
from .diagnostics import AnnotationError, SourceLocation


class TypeKind(Enum):
    BOOL = "bool"
    INTEGER = "integer"
    FLOAT = "float"
    ENUM = "enum"
    STRING = "string"
    FIXED_ARRAY = "fixed_array"
    POINTER = "pointer"
    DYNAMIC_ARRAY = "dynamic_array"
    RECORD = "record"


@dataclass(frozen=True)
class TypeSchema:
    id: str
    kind: TypeKind
    c_type: str
    bits: int | None = None
    signed: bool | None = None
    target: str | None = None
    capacity: int | None = None


@dataclass(frozen=True)
class FieldSchema:
    name: str
    c_type: str
    type_id: str
    key: str
    altkeys: tuple[str, ...]
    required: bool
    flatten: bool
    omitempty: bool
    length_field: str | None
    is_length_metadata: bool
    minimum: str | None
    maximum: str | None
    min_length: int | None
    max_length: int | None
    owns_resources: bool
    location: SourceLocation


@dataclass(frozen=True)
class RecordSchema:
    id: str
    name: str
    c_type: str
    fields: tuple[FieldSchema, ...]
    public: bool
    owns_resources: bool
    location: SourceLocation


@dataclass(frozen=True)
class FunctionSchema:
    name: str
    role: str
    record_id: str | None
    type_name: str
    parameter_types: tuple[str, ...]
    location: SourceLocation


@dataclass(frozen=True)
class SchemaIR:
    types: tuple[TypeSchema, ...]
    records: tuple[RecordSchema, ...]
    functions: tuple[FunctionSchema, ...]

    def type_map(self) -> dict[str, TypeSchema]:
        return {item.id: item for item in self.types}

    def record_map(self) -> dict[str, RecordSchema]:
        return {item.id: item for item in self.records}


_INTEGER_TYPES: dict[str, tuple[int, bool]] = {
    "char": (8, True),
    "signed char": (8, True),
    "unsigned char": (8, False),
    "short": (16, True),
    "short int": (16, True),
    "signed short": (16, True),
    "unsigned short": (16, False),
    "unsigned short int": (16, False),
    "int": (32, True),
    "signed": (32, True),
    "signed int": (32, True),
    "unsigned": (32, False),
    "unsigned int": (32, False),
    "long": (64, True),
    "long int": (64, True),
    "signed long": (64, True),
    "unsigned long": (64, False),
    "unsigned long int": (64, False),
    "long long": (64, True),
    "long long int": (64, True),
    "unsigned long long": (64, False),
    "unsigned long long int": (64, False),
}


def _json_annotation(annotations: tuple[Annotation, ...], location: SourceLocation) -> Annotation | None:
    selected = [annotation for annotation in annotations if annotation.name == "json"]
    if len(selected) > 1:
        raise AnnotationError("a declaration may contain only one @json annotation", location)
    return selected[0] if selected else None


def _one(annotation: Annotation | None, name: str) -> str | None:
    if annotation is None:
        return None
    values = annotation.values(name)
    return values[0] if values else None


def _flag(annotation: Annotation | None, name: str) -> bool:
    return bool(annotation and annotation.values(name))


def _length(annotation: Annotation | None, name: str, location: SourceLocation) -> int | None:
    value = _one(annotation, name)
    if value is None:
        return None
    try:
        result = int(value, 10)
    except ValueError as error:
        raise AnnotationError(f"{name} must be a non-negative integer", location) from error
    if result < 0:
        raise AnnotationError(f"{name} must be a non-negative integer", location)
    return result


class SchemaBuilder:
    def __init__(self, unit: TranslationUnit):
        self.unit = unit
        self.types: dict[str, TypeSchema] = {}
        self.records_by_name = {record.name: record for record in unit.records}
        self.typedefs = {item.name: item for item in unit.typedefs}
        self.enums_by_name = {item.name: item for item in unit.enums}
        self.record_aliases: dict[str, str] = {}
        for item in unit.typedefs:
            match = re.fullmatch(r"struct\s+([A-Za-z_]\w*)", item.type_name.strip())
            if match:
                self.record_aliases[item.name] = match.group(1)
        self.building_records: set[str] = set()
        self.built_records: dict[str, RecordSchema] = {}
        self.public_names: set[str] = set()

    def build(self) -> SchemaIR:
        public_names = {
            record.name
            for record in self.unit.records
            if any(annotation.name == "jsonStruct" for annotation in record.annotations)
        }
        self.public_names = public_names
        for name in sorted(public_names):
            self._build_record(name, public_names)

        functions: list[FunctionSchema] = []
        for function in self.unit.functions:
            roles = [
                annotation.name
                for annotation in function.annotations
                if annotation.name in {"jsonDecode", "jsonCleanup"}
            ]
            for role in roles:
                record_id = self._function_record(function.parameters)
                if record_id is not None:
                    record_name = record_id.removeprefix("record:")
                    self._build_record(record_name, public_names)
                functions.append(
                    FunctionSchema(
                        function.name,
                        role,
                        record_id,
                        function.type_name,
                        tuple(parameter.type_name for parameter in function.parameters),
                        function.location,
                    )
                )

        records = tuple(sorted(self.built_records.values(), key=lambda item: item.id))
        # Resource ownership is a fixed point for recursive records.
        ownership = {record.id: record.owns_resources for record in records}
        changed = True
        while changed:
            changed = False
            for record in records:
                owns = any(self._field_owns(field.type_id, ownership) for field in record.fields)
                if owns != ownership[record.id]:
                    ownership[record.id] = owns
                    changed = True
        records = tuple(
            replace(
                record,
                owns_resources=ownership[record.id],
                fields=tuple(
                    replace(field, owns_resources=self._field_owns(field.type_id, ownership))
                    for field in record.fields
                ),
            )
            for record in records
        )
        return SchemaIR(
            tuple(sorted(self.types.values(), key=lambda item: item.id)),
            records,
            tuple(sorted(functions, key=lambda item: (item.role, item.name))),
        )

    def _function_record(self, parameters: tuple) -> str | None:
        for parameter in reversed(parameters):
            text = parameter.type_name.strip()
            if text.endswith("*"):
                base = text[:-1].strip()
                name = self._record_name(base)
                if name is not None:
                    return f"record:{name}"
        return None

    def _field_owns(self, type_id: str, record_ownership: dict[str, bool]) -> bool:
        item = self.types[type_id]
        if item.kind in {TypeKind.STRING, TypeKind.DYNAMIC_ARRAY}:
            return item.capacity is None
        if item.kind is TypeKind.POINTER:
            return True
        if item.kind is TypeKind.FIXED_ARRAY and item.target:
            return self._field_owns(item.target, record_ownership)
        if item.kind is TypeKind.RECORD:
            return record_ownership.get(item.id, False)
        return False

    def _build_record(self, name: str, public_names: set[str]) -> RecordSchema:
        record_id = f"record:{name}"
        if record_id in self.built_records:
            return self.built_records[record_id]
        if name in self.building_records:
            placeholder = RecordSchema(record_id, name, f"struct {name}", (), name in public_names, False,
                                       self.records_by_name[name].location)
            self.built_records.setdefault(record_id, placeholder)
            return placeholder
        ast_record = self.records_by_name.get(name)
        if ast_record is None:
            raise AnnotationError(f"record {name!r} has no complete definition")
        self.building_records.add(name)
        self.types.setdefault(record_id, TypeSchema(record_id, TypeKind.RECORD, f"struct {name}"))
        fields = [self._build_field(field) for field in ast_record.fields]

        names = {field.name: field for field in fields}
        length_fields = {field.length_field for field in fields if field.length_field is not None}
        for owner in fields:
            if owner.length_field is None:
                continue
            companion = names.get(owner.length_field)
            if companion is None:
                raise AnnotationError(
                    f"array field {owner.name!r} references missing length field {owner.length_field!r}",
                    owner.location,
                )
            companion_type = self.types[companion.type_id]
            if companion_type.kind is not TypeKind.INTEGER or companion_type.signed:
                raise AnnotationError("array length field must be an unsigned integer", companion.location)
        fields = [replace(field, is_length_metadata=field.name in length_fields) for field in fields]
        for field in fields:
            if field.is_length_metadata and field.required:
                raise AnnotationError("an array length metadata field cannot be required", field.location)

        schema = RecordSchema(
            record_id,
            name,
            f"struct {name}",
            tuple(fields),
            name in public_names,
            any(field.owns_resources for field in fields),
            ast_record.location,
        )
        self.built_records[record_id] = schema
        self.building_records.remove(name)
        self._validate_keys(schema)
        return schema

    def _build_field(self, field: AstField) -> FieldSchema:
        annotation = _json_annotation(field.annotations, field.location)
        type_id = self._resolve_type(field.type_name, field.desugared_type, field.location)
        type_schema = self.types[type_id]
        array_kind = _one(annotation, "type")
        length_field = _one(annotation, "len")
        if array_kind is not None and array_kind != "array":
            raise AnnotationError("the only supported @json type is 'array'", field.location)
        if array_kind == "array":
            if type_schema.kind is not TypeKind.POINTER or type_schema.target is None:
                raise AnnotationError("type=array requires a non-string pointer field", field.location)
            if length_field is None:
                raise AnnotationError("a dynamic array requires len=<field>", field.location)
            type_id = self._intern(
                TypeSchema(
                    f"dynamic-array:{type_schema.target}",
                    TypeKind.DYNAMIC_ARRAY,
                    field.type_name,
                    target=type_schema.target,
                )
            )
            type_schema = self.types[type_id]
        elif length_field is not None and type_schema.kind is not TypeKind.FIXED_ARRAY:
            raise AnnotationError("len is only valid for fixed or dynamic arrays", field.location)

        flatten = _flag(annotation, "flatten")
        required = _flag(annotation, "required")
        if flatten:
            if required:
                raise AnnotationError("required cannot be combined with flatten", field.location)
            if type_schema.kind is not TypeKind.RECORD:
                raise AnnotationError("flatten requires a by-value structure field", field.location)
            if any(_one(annotation, name) is not None for name in ("key", "len", "min", "max", "minlen", "maxlen")):
                raise AnnotationError("flatten cannot be combined with key, len, or constraints", field.location)

        minimum = _one(annotation, "min")
        maximum = _one(annotation, "max")
        if minimum is not None or maximum is not None:
            if type_schema.kind not in {TypeKind.INTEGER, TypeKind.FLOAT, TypeKind.ENUM}:
                raise AnnotationError("min/max require a numeric field", field.location)
            for value in (minimum, maximum):
                if value is not None:
                    try:
                        Decimal(value)
                    except InvalidOperation as error:
                        raise AnnotationError("min/max must be numeric", field.location) from error
        min_length = _length(annotation, "minlen", field.location)
        max_length = _length(annotation, "maxlen", field.location)
        if min_length is not None or max_length is not None:
            if type_schema.kind not in {TypeKind.STRING, TypeKind.FIXED_ARRAY, TypeKind.DYNAMIC_ARRAY}:
                raise AnnotationError("minlen/maxlen require a string or array", field.location)
        if min_length is not None and max_length is not None and min_length > max_length:
            raise AnnotationError("minlen cannot exceed maxlen", field.location)

        altkeys = tuple(value for value in (annotation.values("altkey") if annotation else ()) if value is not None)
        key = _one(annotation, "key") or field.name
        return FieldSchema(
            field.name,
            field.type_name,
            type_id,
            key,
            altkeys,
            required,
            flatten,
            _flag(annotation, "omitempty"),
            length_field,
            False,
            minimum,
            maximum,
            min_length,
            max_length,
            self._field_owns(type_id, {}),
            field.location,
        )

    def _validate_keys(self, record: RecordSchema) -> None:
        keys: dict[str, str] = {}

        def add_fields(current: RecordSchema, prefix: str) -> None:
            for field in current.fields:
                if field.is_length_metadata:
                    continue
                if field.flatten:
                    nested = self.built_records.get(field.type_id)
                    if nested is None:
                        nested_name = field.type_id.removeprefix("record:")
                        nested = self._build_record(nested_name, set())
                    add_fields(nested, prefix + field.name + ".")
                    continue
                for key in (field.key, *field.altkeys):
                    previous = keys.get(key)
                    if previous is not None:
                        raise AnnotationError(
                            f"JSON key {key!r} is shared by {previous} and {prefix + field.name}",
                            field.location,
                        )
                    keys[key] = prefix + field.name

        add_fields(record, "")

    def _record_name(self, text: str) -> str | None:
        text = text.strip()
        if text.startswith("struct "):
            return text.removeprefix("struct ").strip()
        if text in self.record_aliases:
            return self.record_aliases[text]
        if text in self.records_by_name:
            return text
        return None

    def _resolve_type(self, original: str, desugared: str | None, location: SourceLocation) -> str:
        text = re.sub(r"\b(const|volatile|restrict)\b", "", original).strip()
        text = re.sub(r"\s+", " ", text)
        array_match = re.fullmatch(r"(.+)\[(\d+)\]", text)
        if array_match:
            element_text, capacity_text = array_match.groups()
            capacity = int(capacity_text)
            if capacity <= 0:
                raise AnnotationError("zero-length and flexible C arrays are not supported", location)
            if element_text.strip() == "char":
                return self._intern(
                    TypeSchema(f"string:fixed:{capacity}", TypeKind.STRING, text, capacity=capacity)
                )
            target = self._resolve_type(element_text, None, location)
            return self._intern(
                TypeSchema(f"fixed-array:{capacity}:{target}", TypeKind.FIXED_ARRAY, text, target=target, capacity=capacity)
            )
        if text.endswith("*"):
            target_text = text[:-1].strip()
            if target_text == "char":
                return self._intern(TypeSchema("string:pointer", TypeKind.STRING, text))
            target = self._resolve_type(target_text, None, location)
            return self._intern(TypeSchema(f"pointer:{target}", TypeKind.POINTER, text, target=target))
        if text == "_Bool" or text == "bool":
            return self._intern(TypeSchema("bool", TypeKind.BOOL, text, bits=8, signed=False))
        builtin = desugared.strip() if desugared and desugared.strip() in _INTEGER_TYPES else text
        if builtin in _INTEGER_TYPES:
            bits, signed = _INTEGER_TYPES[builtin]
            prefix = "i" if signed else "u"
            return self._intern(TypeSchema(f"integer:{prefix}{bits}", TypeKind.INTEGER, text, bits, signed))
        if builtin in {"float", "double"}:
            bits = 32 if builtin == "float" else 64
            return self._intern(TypeSchema(f"float:{bits}", TypeKind.FLOAT, text, bits=bits, signed=True))
        record_name = self._record_name(text)
        if record_name is not None:
            self._build_record(record_name, self.public_names)
            record_id = f"record:{record_name}"
            self.types.setdefault(record_id, TypeSchema(record_id, TypeKind.RECORD, text))
            return record_id
        enum_name = text.removeprefix("enum ").strip()
        if enum_name in self.enums_by_name:
            enum = self.enums_by_name[enum_name]
            underlying = enum.integer_type or "int"
            bits, signed = _INTEGER_TYPES.get(underlying, (32, True))
            return self._intern(
                TypeSchema(f"enum:{enum_name}", TypeKind.ENUM, text, bits=bits, signed=signed)
            )
        alias = self.typedefs.get(text)
        if alias is not None and alias.type_name != text:
            return self._resolve_type(alias.type_name, alias.desugared_type, location)
        raise AnnotationError(f"unsupported C type {original!r}", location)

    def _intern(self, schema: TypeSchema) -> str:
        self.types.setdefault(schema.id, schema)
        return schema.id


def build_schema_ir(unit: TranslationUnit) -> SchemaIR:
    return SchemaBuilder(unit).build()


def format_schema_ir(schema: SchemaIR) -> str:
    lines = ["SchemaIR"]
    type_map = schema.type_map()
    for record in schema.records:
        attributes = ["public"] if record.public else []
        if record.owns_resources:
            attributes.append("owns-resources")
        suffix = f" [{', '.join(attributes)}]" if attributes else ""
        lines.append(f"  record {record.id}{suffix}")
        for field in record.fields:
            field_type = type_map[field.type_id]
            flags: list[str] = []
            if field.required:
                flags.append("required")
            if field.flatten:
                flags.append("flatten")
            if field.is_length_metadata:
                flags.append("length-metadata")
            if field.owns_resources:
                flags.append("owns-resources")
            suffix = f" [{', '.join(flags)}]" if flags else ""
            lines.append(f"    field {field.name}: {field_type.id} key={field.key!r}{suffix}")
            if field.altkeys:
                lines.append(f"      altkeys: {', '.join(repr(key) for key in field.altkeys)}")
            constraints = []
            for name, value in (
                ("min", field.minimum),
                ("max", field.maximum),
                ("minlen", field.min_length),
                ("maxlen", field.max_length),
                ("len", field.length_field),
            ):
                if value is not None:
                    constraints.append(f"{name}={value}")
            if constraints:
                lines.append("      constraints: " + ", ".join(constraints))
    if schema.functions:
        lines.append("  functions")
        for function in schema.functions:
            lines.append(f"    {function.role} {function.name} -> {function.record_id or '?'}")
    return "\n".join(lines)
