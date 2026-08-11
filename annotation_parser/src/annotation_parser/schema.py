from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum

from .annotations import Annotation
from .clang_frontend import (
    AstField,
    AstRecord,
    AstType,
    AstTypeKind,
    BasicType,
    TranslationUnit,
)
from .diagnostics import AnnotationError, SourceLocation


class TypeKind(Enum):
    BOOL = "bool"
    INTEGER = "integer"
    FLOAT = "float"
    ENUM = "enum"
    STRING = "string"
    FIXED_ARRAY = "fixed_array"
    DYNAMIC_ARRAY = "dynamic_array"
    RECORD = "record"
    POINTER = "pointer"


class RecordShape(Enum):
    OBJECT = "object"
    ARRAY = "array"


@dataclass(frozen=True)
class TypeSchema:
    id: str
    kind: TypeKind
    c_type: str
    bits: int | None = None
    signed: bool | None = None
    target: str | None = None
    capacity: int | None = None
    owns_resources: bool = False
    basic_type: BasicType | None = None


@dataclass(frozen=True)
class FieldSchema:
    id: str
    record_id: str
    name: str
    c_type: str
    type_id: str
    location: SourceLocation
    key: str
    altkeys: tuple[str, ...] = ()
    required: bool = False
    flatten: bool = False
    key_explicit: bool = False
    minimum: str | None = None
    maximum: str | None = None
    min_length: int | None = None
    max_length: int | None = None
    length_field_id: str | None = None
    dynamic_array: bool = False
    omitempty: bool = False
    ignored: bool = False
    owns_resources: bool = False


@dataclass(frozen=True)
class ArrayLayout:
    elems_field_id: str
    element_type_id: str
    length_field_id: str | None
    capacity_field_id: str | None
    ignored_field_ids: tuple[str, ...]


@dataclass(frozen=True)
class RecordSchema:
    id: str
    name: str
    c_type: str
    fields: tuple[FieldSchema, ...]
    location: SourceLocation
    shape: RecordShape = RecordShape.OBJECT
    array: ArrayLayout | None = None
    owns_resources: bool = False


@dataclass(frozen=True)
class FunctionSchema:
    id: str
    name: str
    role: str
    record_id: str
    return_c_type: str
    parameter_c_types: tuple[str, ...]
    location: SourceLocation


@dataclass(frozen=True)
class Schema:
    types: tuple[TypeSchema, ...]
    records: tuple[RecordSchema, ...]
    functions: tuple[FunctionSchema, ...]
    public_record_ids: tuple[str, ...]

    def type_map(self) -> dict[str, TypeSchema]:
        return {item.id: item for item in self.types}

    def record_map(self) -> dict[str, RecordSchema]:
        return {item.id: item for item in self.records}

    def field_map(self) -> dict[str, FieldSchema]:
        return {field.id: field for record in self.records for field in record.fields}

    def function_map(self) -> dict[str, FunctionSchema]:
        return {item.id: item for item in self.functions}

    def metadata_field_ids(self) -> frozenset[str]:
        return frozenset(
            field.length_field_id
            for record in self.records
            for field in record.fields
            if field.length_field_id is not None
        )


def _find_annotation(
    annotations: tuple[Annotation, ...], name: str, location: SourceLocation
) -> Annotation | None:
    matches = tuple(item for item in annotations if item.name == name)
    if len(matches) > 1:
        raise AnnotationError(
            f"a declaration may contain only one @{name} annotation", location
        )
    return matches[0] if matches else None


def _argument(annotation: Annotation | None, name: str) -> str | None:
    values = annotation.values(name) if annotation else ()
    return values[0] if values else None


def _flag(annotation: Annotation | None, name: str) -> bool:
    return bool(annotation and annotation.values(name))


class SchemaBuilder:
    def __init__(self, unit: TranslationUnit):
        self.unit = unit
        self.ast_records = {item.name: item for item in unit.records}
        self.reachable: set[str] = set()
        self.types: dict[str, TypeSchema] = {}
        self.records: dict[str, RecordSchema] = {}

    def build(self) -> Schema:
        public = tuple(
            sorted(
                f"record:{record.name}"
                for record in self.unit.records
                if _find_annotation(record.annotations, "jsonStruct", record.location)
                is not None
            )
        )
        raw_functions, function_roots = self._find_functions()
        roots = {item.removeprefix("record:") for item in public}
        roots.update(function_roots)
        for name in sorted(roots):
            self._collect_record(name)
        self._build_records()
        self._resolve_array_layouts()
        functions = self._build_functions(raw_functions, set(public))
        self._apply_ownership()
        return Schema(
            tuple(sorted(self.types.values(), key=lambda item: item.id)),
            tuple(sorted(self.records.values(), key=lambda item: item.id)),
            tuple(sorted(functions, key=lambda item: (item.role, item.id))),
            public,
        )

    def _find_functions(self):
        result = []
        roots: set[str] = set()
        known = set(self.ast_records)
        for function in self.unit.functions:
            for role in ("jsonDecode", "jsonCleanup"):
                if (
                    _find_annotation(function.annotations, role, function.location)
                    is None
                ):
                    continue
                record_name = None
                if len(function.parameters) >= 2:
                    item = function.parameters[1].type
                    if (
                        item.kind is AstTypeKind.POINTER
                        and item.target is not None
                        and item.target.kind is AstTypeKind.RECORD
                        and item.target.name in known
                    ):
                        record_name = item.target.name
                        roots.add(record_name)
                result.append((function, role, record_name))
        return result, roots

    def _collect_record(self, name: str) -> None:
        if name in self.reachable or name not in self.ast_records:
            return
        self.reachable.add(name)
        for field in self.ast_records[name].fields:
            self._collect_type_records(field.type)

    def _collect_type_records(self, item: AstType) -> None:
        if item.kind is AstTypeKind.RECORD and item.name is not None:
            self._collect_record(item.name)
        if item.target is not None:
            self._collect_type_records(item.target)

    def _build_records(self) -> None:
        for name in sorted(self.reachable):
            ast_record = self.ast_records[name]
            record_id = f"record:{name}"
            self.types.setdefault(
                record_id,
                TypeSchema(
                    record_id,
                    TypeKind.RECORD,
                    ast_record.c_type or f"struct {name}",
                ),
            )
        for name in sorted(self.reachable):
            ast_record = self.ast_records[name]
            record_id = f"record:{name}"
            annotation = _find_annotation(
                ast_record.annotations, "jsonStruct", ast_record.location
            )
            if _flag(annotation, "asarray"):
                elems_name = _argument(annotation, "elems")
                elems = next(
                    (field for field in ast_record.fields if field.name == elems_name),
                    None,
                )
                if elems is not None and (
                    elems.type.kind is not AstTypeKind.POINTER
                    or elems.type.target is None
                    or elems.type.target.kind is AstTypeKind.VOID
                ):
                    raise AnnotationError(
                        "array record elems field must be a non-void pointer",
                        elems.location,
                    )
            fields = tuple(
                self._build_field(record_id, item) for item in ast_record.fields
            )
            self.records[record_id] = RecordSchema(
                record_id,
                name,
                ast_record.c_type or f"struct {name}",
                fields,
                ast_record.location,
            )

    def _build_field(self, record_id: str, field: AstField) -> FieldSchema:
        annotation = _find_annotation(field.annotations, "json", field.location)
        dynamic = _argument(annotation, "type") == "array"
        type_id = self._intern_type(field.type, dynamic)
        minimum = _argument(annotation, "min")
        maximum = _argument(annotation, "max")
        min_length = self._length(annotation, "minlen", field)
        max_length = self._length(annotation, "maxlen", field)
        altkeys = tuple(
            value
            for value in (annotation.values("altkey") if annotation else ())
            if value is not None
        )
        explicit_key = _argument(annotation, "key") is not None
        return FieldSchema(
            f"field:{record_id.removeprefix('record:')}.{field.name}",
            record_id,
            field.name,
            field.type.c_type,
            type_id,
            field.location,
            _argument(annotation, "key") or field.name,
            altkeys,
            _flag(annotation, "required"),
            _flag(annotation, "flatten"),
            explicit_key,
            minimum,
            maximum,
            min_length,
            max_length,
            dynamic_array=dynamic,
            omitempty=_flag(annotation, "omitempty"),
        )

    def _length(
        self, annotation: Annotation | None, name: str, field: AstField
    ) -> int | None:
        value = _argument(annotation, name)
        if value is None:
            return None
        try:
            result = int(value, 10)
        except ValueError as error:
            raise AnnotationError(
                f"{name} must be a non-negative integer", field.location
            ) from error
        if result < 0:
            raise AnnotationError(
                f"{name} must be a non-negative integer", field.location
            )
        return result

    def _intern_type(self, item: AstType, dynamic: bool = False) -> str:
        if dynamic:
            if (
                item.kind is not AstTypeKind.POINTER
                or item.target is None
                or (
                    item.target.kind is AstTypeKind.INTEGER
                    and item.target.name == "char"
                )
            ):
                raise AnnotationError("type=array requires a non-string pointer field")
            target = self._intern_type(item.target)
            value = TypeSchema(
                f"dynamic-array:{target}",
                TypeKind.DYNAMIC_ARRAY,
                item.c_type,
                target=target,
            )
        elif item.kind is AstTypeKind.BOOL:
            value = TypeSchema(
                "basic:bool",
                TypeKind.BOOL,
                item.c_type,
                8,
                False,
                basic_type=BasicType.BOOL,
            )
        elif item.kind is AstTypeKind.INTEGER:
            if item.basic_type is None:
                raise AnnotationError(
                    f"missing basic type identity for {item.c_type!r}"
                )
            bits = item.bits or 32
            signed = bool(item.signed)
            value = TypeSchema(
                f"basic:{item.basic_type.value}",
                TypeKind.INTEGER,
                item.c_type,
                bits,
                signed,
                basic_type=item.basic_type,
            )
        elif item.kind is AstTypeKind.FLOAT:
            if item.basic_type is None:
                raise AnnotationError(
                    f"missing basic type identity for {item.c_type!r}"
                )
            bits = item.bits or 64
            value = TypeSchema(
                f"basic:{item.basic_type.value}",
                TypeKind.FLOAT,
                item.c_type,
                bits,
                True,
                basic_type=item.basic_type,
            )
        elif item.kind is AstTypeKind.ENUM:
            value = TypeSchema(
                f"enum:{item.name}",
                TypeKind.ENUM,
                item.c_type,
                item.bits or 32,
                bool(item.signed),
                basic_type=item.basic_type or BasicType.INT,
            )
        elif item.kind is AstTypeKind.RECORD and item.name is not None:
            record = self.ast_records.get(item.name)
            c_type = record.c_type if record and record.c_type else item.c_type
            value = TypeSchema(f"record:{item.name}", TypeKind.RECORD, c_type)
        elif (
            item.kind in {AstTypeKind.POINTER, AstTypeKind.ARRAY}
            and item.target is not None
        ):
            is_char = item.target.kind is AstTypeKind.INTEGER and item.target.name in {
                "char",
                "signed char",
                "unsigned char",
            }
            if is_char:
                if item.kind is AstTypeKind.POINTER:
                    value = TypeSchema("string:pointer", TypeKind.STRING, item.c_type)
                else:
                    if item.capacity is None or item.capacity <= 0:
                        raise AnnotationError(
                            "zero-length and flexible C arrays are not supported"
                        )
                    value = TypeSchema(
                        f"string:fixed:{item.capacity}",
                        TypeKind.STRING,
                        item.c_type,
                        capacity=item.capacity,
                    )
            else:
                target = self._intern_type(item.target)
                if item.kind is AstTypeKind.POINTER:
                    value = TypeSchema(
                        f"pointer:{target}",
                        TypeKind.POINTER,
                        item.c_type,
                        target=target,
                    )
                else:
                    if item.capacity is None or item.capacity <= 0:
                        raise AnnotationError(
                            "zero-length and flexible C arrays are not supported"
                        )
                    value = TypeSchema(
                        f"fixed-array:{item.capacity}:{target}",
                        TypeKind.FIXED_ARRAY,
                        item.c_type,
                        target=target,
                        capacity=item.capacity,
                    )
        else:
            raise AnnotationError(f"unsupported C type {item.c_type!r}")
        self.types.setdefault(value.id, value)
        return value.id

    def _resolve_array_layouts(self) -> None:
        for record_id, record in tuple(self.records.items()):
            ast_record = self.ast_records[record.name]
            ast_fields = {item.name: item for item in ast_record.fields}
            fields = {item.name: item for item in record.fields}
            updated = dict(fields)
            for name, field in fields.items():
                ast_field = ast_fields[name]
                annotation = _find_annotation(
                    ast_field.annotations, "json", ast_field.location
                )
                kind = _argument(annotation, "type")
                length_name = _argument(annotation, "len")
                if kind is not None and kind != "array":
                    raise AnnotationError(
                        "the only supported @json type is 'array'", field.location
                    )
                if kind == "array" and length_name is None:
                    raise AnnotationError(
                        "a dynamic array requires len=<field>", field.location
                    )
                if (
                    kind != "array"
                    and length_name is not None
                    and self.types[field.type_id].kind is not TypeKind.FIXED_ARRAY
                ):
                    raise AnnotationError(
                        "len is only valid for fixed or dynamic arrays", field.location
                    )
                if length_name is not None:
                    length = fields.get(length_name)
                    if length is None:
                        raise AnnotationError(
                            f"array field {name!r} references missing length field {length_name!r}",
                            field.location,
                        )
                    updated[name] = replace(field, length_field_id=length.id)
            record_annotation = _find_annotation(
                ast_record.annotations, "jsonStruct", ast_record.location
            )
            if (
                record_annotation
                and record_annotation.arguments
                and not _flag(record_annotation, "asarray")
            ):
                raise AnnotationError(
                    "parameterized @jsonStruct requires the asarray flag",
                    ast_record.location,
                )
            layout = None
            shape = RecordShape.OBJECT
            if _flag(record_annotation, "asarray"):
                layout = self._array_record_layout(ast_record, tuple(updated.values()))
                shape = RecordShape.ARRAY
                ignored = set(layout.ignored_field_ids)
                updated = {
                    name: replace(field, ignored=field.id in ignored)
                    for name, field in updated.items()
                }
            self.records[record_id] = replace(
                record,
                fields=tuple(updated[field.name] for field in record.fields),
                shape=shape,
                array=layout,
            )

    def _array_record_layout(
        self, ast_record: AstRecord, fields: tuple[FieldSchema, ...]
    ) -> ArrayLayout:
        annotation = _find_annotation(
            ast_record.annotations, "jsonStruct", ast_record.location
        )
        elems_name = _argument(annotation, "elems")
        if elems_name is None:
            raise AnnotationError(
                "@jsonStruct(asarray) requires elems=<field>", ast_record.location
            )
        names = {item.name: item for item in fields}
        length_name = _argument(annotation, "len")
        capacity_name = _argument(annotation, "cap")
        references = [item for item in (elems_name, length_name, capacity_name) if item]
        if len(references) != len(set(references)):
            raise AnnotationError(
                "array record elems, len, and cap fields must be distinct",
                ast_record.location,
            )
        for name in references:
            if name not in names:
                raise AnnotationError(
                    f"array record references missing field {name!r}",
                    ast_record.location,
                )
        elems = names[elems_name]
        elems_type = self.types[elems.type_id]
        if elems_type.kind is not TypeKind.POINTER or elems_type.target is None:
            raise AnnotationError(
                "array record elems field must be a non-void pointer", elems.location
            )
        length = names.get(length_name) if length_name else None
        capacity = names.get(capacity_name) if capacity_name else None
        storage = {item.id for item in (elems, length, capacity) if item is not None}
        return ArrayLayout(
            elems.id,
            elems_type.target,
            length.id if length else None,
            capacity.id if capacity else None,
            tuple(sorted(item.id for item in fields if item.id not in storage)),
        )

    def _build_functions(
        self, raw_functions, public: set[str]
    ) -> tuple[FunctionSchema, ...]:
        cleanups = {
            f"record:{record_name}"
            for _, role, record_name in raw_functions
            if role == "jsonCleanup" and record_name is not None
        }
        result = []
        for function, role, record_name in raw_functions:
            if role == "jsonDecode":
                valid_return = function.return_type.kind is AstTypeKind.BOOL
                expected_first = "json_parser"
                signature = "@jsonDecode requires bool function(json_parser *, T *)"
            else:
                valid_return = function.return_type.kind is AstTypeKind.VOID
                expected_first = "json_allocator"
                signature = "@jsonCleanup requires void function(json_allocator *, T *)"
            if not valid_return or len(function.parameters) != 2:
                raise AnnotationError(signature, function.location)
            first = function.parameters[0].type
            if (
                first.kind is not AstTypeKind.POINTER
                or first.target is None
                or first.target.name != expected_first
            ):
                raise AnnotationError(
                    f"the first @{role} parameter must be {expected_first} *",
                    function.location,
                )
            if record_name is None:
                raise AnnotationError(
                    f"the second @{role} parameter must point to a known structure",
                    function.location,
                )
            record_id = f"record:{record_name}"
            if role == "jsonDecode" and record_id not in public:
                raise AnnotationError(
                    "the @jsonDecode target must have @jsonStruct", function.location
                )
            if role == "jsonDecode" and record_id not in cleanups:
                raise AnnotationError(
                    "each @jsonDecode target requires an @jsonCleanup function",
                    function.location,
                )
            result.append(
                FunctionSchema(
                    f"function:{function.name}:{role}",
                    function.name,
                    role,
                    record_id,
                    function.return_type.c_type,
                    tuple(item.type.c_type for item in function.parameters),
                    function.location,
                )
            )
        return tuple(result)

    def _apply_ownership(self) -> None:
        metadata = {
            field.length_field_id
            for record in self.records.values()
            for field in record.fields
            if field.length_field_id is not None
        }
        record_ownership = {
            record.id: record.shape is RecordShape.ARRAY
            for record in self.records.values()
        }

        def owns(type_id: str) -> bool:
            item = self.types[type_id]
            if item.kind in {TypeKind.POINTER, TypeKind.DYNAMIC_ARRAY}:
                return True
            if item.kind is TypeKind.STRING:
                return item.capacity is None
            if item.kind is TypeKind.FIXED_ARRAY and item.target:
                return owns(item.target)
            if item.kind is TypeKind.RECORD:
                return record_ownership.get(item.id, False)
            return False

        changed = True
        while changed:
            changed = False
            for record in self.records.values():
                value = record.shape is RecordShape.ARRAY or any(
                    owns(field.type_id)
                    for field in record.fields
                    if not field.ignored and field.id not in metadata
                )
                if value != record_ownership[record.id]:
                    record_ownership[record.id] = value
                    changed = True
        for record_id, record in tuple(self.records.items()):
            fields = tuple(
                replace(
                    field,
                    owns_resources=(
                        False
                        if field.ignored or field.id in metadata
                        else owns(field.type_id)
                    ),
                )
                for field in record.fields
            )
            self.records[record_id] = replace(
                record, fields=fields, owns_resources=record_ownership[record_id]
            )
        self.types = {
            type_id: replace(item, owns_resources=owns(type_id))
            for type_id, item in self.types.items()
        }


def build_schema(unit: TranslationUnit) -> Schema:
    from .schema_validator import validate_annotations, validate_schema

    validate_annotations(unit)
    schema = SchemaBuilder(unit).build()
    validate_schema(schema)
    return schema


def format_schema(schema: Schema) -> str:
    lines = ["Schema"]
    for item in schema.types:
        parts = [f"kind={item.kind.value}", f"c-type={item.c_type!r}"]
        if item.target:
            parts.append(f"target={item.target}")
        if item.basic_type is not None:
            parts.append(f"basic={item.basic_type.value}")
        if item.capacity is not None:
            parts.append(f"capacity={item.capacity}")
        if item.owns_resources:
            parts.append("owns-resources")
        lines.append(f"  type {item.id} " + " ".join(parts))
    for record in schema.records:
        lines.append(
            f"  record {record.id} c-type={record.c_type!r} shape={record.shape.value} "
            f"owns={str(record.owns_resources).lower()}"
        )
        if record.array is not None:
            parts = [
                f"elems={record.array.elems_field_id}",
                f"element={record.array.element_type_id}",
            ]
            if record.array.length_field_id:
                parts.append(f"len={record.array.length_field_id}")
            if record.array.capacity_field_id:
                parts.append(f"cap={record.array.capacity_field_id}")
            if record.array.ignored_field_ids:
                parts.append(f"ignored={record.array.ignored_field_ids!r}")
            lines.append("    array " + " ".join(parts))
        for field in record.fields:
            flags = []
            if field.required:
                flags.append("required")
            if field.flatten:
                flags.append("flatten")
            if field.omitempty:
                flags.append("omitempty")
            if field.ignored:
                flags.append("ignored")
            if field.owns_resources:
                flags.append("owns-resources")
            suffix = f" [{' '.join(flags)}]" if flags else ""
            lines.append(
                f"    field {field.id} type={field.type_id} key={field.key!r}"
                + (f" altkeys={field.altkeys!r}" if field.altkeys else "")
                + (f" len={field.length_field_id}" if field.length_field_id else "")
                + suffix
            )
            constraints = [
                f"{name}={value}"
                for name, value in (
                    ("min", field.minimum),
                    ("max", field.maximum),
                    ("minlen", field.min_length),
                    ("maxlen", field.max_length),
                )
                if value is not None
            ]
            if constraints:
                lines.append("      constraints " + " ".join(constraints))
    for function in schema.functions:
        lines.append(f"  {function.role} {function.name} -> {function.record_id}")
    return "\n".join(lines)
