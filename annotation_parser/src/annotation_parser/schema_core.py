from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .clang_frontend import AstRecord, AstType, AstTypeKind, TranslationUnit
from .diagnostics import SourceLocation


class CoreTypeKind(Enum):
    VOID = "void"
    BOOL = "bool"
    INTEGER = "integer"
    FLOAT = "float"
    ENUM = "enum"
    RECORD = "record"
    POINTER = "pointer"
    FIXED_ARRAY = "fixed_array"
    OPAQUE = "opaque"


@dataclass(frozen=True)
class CoreTypeSchema:
    id: str
    kind: CoreTypeKind
    c_type: str
    bits: int | None = None
    signed: bool | None = None
    name: str | None = None
    target: str | None = None
    capacity: int | None = None


@dataclass(frozen=True)
class CoreFieldSchema:
    id: str
    record_id: str
    name: str
    c_type: str
    type_id: str
    location: SourceLocation


@dataclass(frozen=True)
class CoreRecordSchema:
    id: str
    name: str
    c_type: str
    fields: tuple[CoreFieldSchema, ...]
    location: SourceLocation


@dataclass(frozen=True)
class CoreFunctionSchema:
    id: str
    name: str
    return_type_id: str
    return_c_type: str
    parameter_type_ids: tuple[str, ...]
    parameter_c_types: tuple[str, ...]
    location: SourceLocation


@dataclass(frozen=True)
class CoreSchemaIR:
    types: tuple[CoreTypeSchema, ...]
    records: tuple[CoreRecordSchema, ...]
    functions: tuple[CoreFunctionSchema, ...]

    def type_map(self) -> dict[str, CoreTypeSchema]:
        return {item.id: item for item in self.types}

    def record_map(self) -> dict[str, CoreRecordSchema]:
        return {item.id: item for item in self.records}

    def field_map(self) -> dict[str, CoreFieldSchema]:
        return {field.id: field for record in self.records for field in record.fields}

    def function_map(self) -> dict[str, CoreFunctionSchema]:
        return {item.id: item for item in self.functions}


class CoreSchemaBuilder:
    def __init__(self, unit: TranslationUnit):
        self.unit = unit
        self.records_by_name = {record.name: record for record in unit.records}
        self.types: dict[str, CoreTypeSchema] = {}
        self.records: dict[str, CoreRecordSchema] = {}
        self.building: set[str] = set()

    def build(
        self, root_record_names: tuple[str, ...], function_names: tuple[str, ...]
    ) -> CoreSchemaIR:
        for name in sorted(set(root_record_names)):
            self._build_record(name)
        selected = {name for name in function_names}
        functions = []
        for function in self.unit.functions:
            if function.name not in selected:
                continue
            return_type_id = self._intern_type(function.return_type)
            parameter_type_ids = tuple(
                self._intern_type(parameter.type) for parameter in function.parameters
            )
            functions.append(
                CoreFunctionSchema(
                    f"function:{function.name}",
                    function.name,
                    return_type_id,
                    function.return_type.c_type,
                    parameter_type_ids,
                    tuple(parameter.type.c_type for parameter in function.parameters),
                    function.location,
                )
            )
        return CoreSchemaIR(
            tuple(sorted(self.types.values(), key=lambda item: item.id)),
            tuple(sorted(self.records.values(), key=lambda item: item.id)),
            tuple(sorted(functions, key=lambda item: item.id)),
        )

    def _build_record(self, name: str) -> str:
        record_id = f"record:{name}"
        if record_id in self.records:
            return record_id
        ast_record = self.records_by_name.get(name)
        if ast_record is None:
            return record_id
        if name in self.building:
            return record_id
        self.building.add(name)
        self.types.setdefault(
            record_id,
            CoreTypeSchema(
                record_id,
                CoreTypeKind.RECORD,
                ast_record.c_type or f"struct {name}",
                name=name,
            ),
        )
        fields = []
        for ast_field in ast_record.fields:
            type_id = self._intern_type(ast_field.type)
            fields.append(
                CoreFieldSchema(
                    f"field:{name}.{ast_field.name}",
                    record_id,
                    ast_field.name,
                    ast_field.type.c_type,
                    type_id,
                    ast_field.location,
                )
            )
            self._discover_records(ast_field.type)
        self.records[record_id] = CoreRecordSchema(
            record_id,
            name,
            ast_record.c_type or f"struct {name}",
            tuple(fields),
            ast_record.location,
        )
        self.building.remove(name)
        return record_id

    def _discover_records(self, ast_type: AstType) -> None:
        if ast_type.kind is AstTypeKind.RECORD and ast_type.name in self.records_by_name:
            self._build_record(ast_type.name)
        if ast_type.target is not None:
            self._discover_records(ast_type.target)

    def _intern_type(self, item: AstType) -> str:
        if item.kind is AstTypeKind.VOID:
            schema = CoreTypeSchema("void", CoreTypeKind.VOID, item.c_type, name=item.name)
        elif item.kind is AstTypeKind.BOOL:
            schema = CoreTypeSchema("bool", CoreTypeKind.BOOL, item.c_type, 8, False, item.name)
        elif item.kind is AstTypeKind.INTEGER:
            bits = item.bits or 32
            signed = bool(item.signed)
            schema = CoreTypeSchema(
                f"integer:{'i' if signed else 'u'}{bits}",
                CoreTypeKind.INTEGER,
                item.c_type,
                bits,
                signed,
                item.name,
            )
        elif item.kind is AstTypeKind.FLOAT:
            bits = item.bits or 64
            schema = CoreTypeSchema(
                f"float:{bits}", CoreTypeKind.FLOAT, item.c_type, bits, True, item.name
            )
        elif item.kind is AstTypeKind.ENUM:
            schema = CoreTypeSchema(
                f"enum:{item.name}",
                CoreTypeKind.ENUM,
                item.c_type,
                item.bits or 32,
                bool(item.signed),
                item.name,
            )
        elif item.kind is AstTypeKind.RECORD:
            schema = CoreTypeSchema(
                f"record:{item.name}", CoreTypeKind.RECORD, item.c_type, name=item.name
            )
        elif item.kind in {AstTypeKind.POINTER, AstTypeKind.ARRAY} and item.target is not None:
            target = self._intern_type(item.target)
            if item.kind is AstTypeKind.POINTER:
                schema = CoreTypeSchema(
                    f"pointer:{target}", CoreTypeKind.POINTER, item.c_type, target=target
                )
            else:
                capacity = item.capacity
                schema = CoreTypeSchema(
                    f"fixed-array:{capacity}:{target}",
                    CoreTypeKind.FIXED_ARRAY,
                    item.c_type,
                    target=target,
                    capacity=capacity,
                )
        else:
            name = item.name or item.c_type
            schema = CoreTypeSchema(
                f"opaque:{name}", CoreTypeKind.OPAQUE, item.c_type, name=name
            )
        self.types.setdefault(schema.id, schema)
        return schema.id


def build_core_schema(
    unit: TranslationUnit, root_record_names: tuple[str, ...], function_names: tuple[str, ...]
) -> CoreSchemaIR:
    return CoreSchemaBuilder(unit).build(root_record_names, function_names)


def format_core_schema(core: CoreSchemaIR) -> str:
    lines = ["core"]
    for item in core.types:
        parts = [f"kind={item.kind.value}", f"c-type={item.c_type!r}"]
        if item.target:
            parts.append(f"target={item.target}")
        if item.capacity is not None:
            parts.append(f"capacity={item.capacity}")
        lines.append(f"  type {item.id} " + " ".join(parts))
    for record in core.records:
        lines.append(f"  record {record.id} c-type={record.c_type!r}")
        for field in record.fields:
            lines.append(f"    field {field.id} type={field.type_id} c-type={field.c_type!r}")
    for function in core.functions:
        lines.append(
            f"  function {function.id} return={function.return_type_id} "
            f"parameters={function.parameter_type_ids!r}"
        )
    return "\n".join(lines)
