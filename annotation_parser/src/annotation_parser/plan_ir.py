from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .schema_ir import FieldSchema, RecordSchema, SchemaIR, TypeKind


class DecodeOperation(Enum):
    BOOL = "decode-bool"
    INTEGER = "decode-integer"
    FLOAT = "decode-float"
    ENUM = "decode-enum"
    STRING = "decode-string"
    FIXED_ARRAY = "decode-fixed-array"
    DYNAMIC_ARRAY = "decode-dynamic-array"
    RECORD = "decode-record"
    POINTER = "decode-pointer"


class ReleaseOperation(Enum):
    STRING = "release-string"
    FIXED_ARRAY = "release-fixed-array"
    DYNAMIC_ARRAY = "release-dynamic-array"
    RECORD = "release-record"
    POINTER = "release-pointer"


@dataclass(frozen=True)
class DecodeValuePlan:
    type_id: str
    operation: DecodeOperation
    target_type_id: str | None
    nullable: bool
    capacity: int | None


@dataclass(frozen=True)
class DecodeFieldPlan:
    path: tuple[str, ...]
    keys: tuple[str, ...]
    seen_index: int
    required: bool
    value: DecodeValuePlan
    length_path: tuple[str, ...] | None
    minimum: str | None
    maximum: str | None
    min_length: int | None
    max_length: int | None


@dataclass(frozen=True)
class DecodeObjectPlan:
    record_id: str
    fields: tuple[DecodeFieldPlan, ...]
    required_seen: tuple[int, ...]
    rollback_record_id: str


@dataclass(frozen=True)
class DecodeEntryPlan:
    function_name: str
    record_id: str | None


@dataclass(frozen=True)
class DecodePlan:
    values: tuple[DecodeValuePlan, ...]
    objects: tuple[DecodeObjectPlan, ...]
    entries: tuple[DecodeEntryPlan, ...]


@dataclass(frozen=True)
class ReleaseFieldPlan:
    path: tuple[str, ...]
    type_id: str
    operation: ReleaseOperation
    target_type_id: str | None
    length_path: tuple[str, ...] | None
    capacity: int | None


@dataclass(frozen=True)
class ReleaseObjectPlan:
    record_id: str
    fields: tuple[ReleaseFieldPlan, ...]
    clear_after_release: bool


@dataclass(frozen=True)
class ReleaseEntryPlan:
    function_name: str
    record_id: str | None


@dataclass(frozen=True)
class ReleasePlan:
    objects: tuple[ReleaseObjectPlan, ...]
    entries: tuple[ReleaseEntryPlan, ...]


_DECODE_OPERATIONS = {
    TypeKind.BOOL: DecodeOperation.BOOL,
    TypeKind.INTEGER: DecodeOperation.INTEGER,
    TypeKind.FLOAT: DecodeOperation.FLOAT,
    TypeKind.ENUM: DecodeOperation.ENUM,
    TypeKind.STRING: DecodeOperation.STRING,
    TypeKind.FIXED_ARRAY: DecodeOperation.FIXED_ARRAY,
    TypeKind.DYNAMIC_ARRAY: DecodeOperation.DYNAMIC_ARRAY,
    TypeKind.RECORD: DecodeOperation.RECORD,
    TypeKind.POINTER: DecodeOperation.POINTER,
}


def _decode_value(type_id: str, schema: SchemaIR) -> DecodeValuePlan:
    item = schema.type_map()[type_id]
    return DecodeValuePlan(
        type_id,
        _DECODE_OPERATIONS[item.kind],
        item.target,
        item.kind in {TypeKind.STRING, TypeKind.DYNAMIC_ARRAY, TypeKind.POINTER} and item.capacity is None,
        item.capacity,
    )


def _decode_fields(
    record: RecordSchema,
    schema: SchemaIR,
    prefix: tuple[str, ...] = (),
) -> list[DecodeFieldPlan]:
    records = schema.record_map()
    result: list[DecodeFieldPlan] = []
    for field in record.fields:
        if field.is_length_metadata:
            continue
        path = prefix + (field.name,)
        if field.flatten:
            nested = records[field.type_id]
            result.extend(_decode_fields(nested, schema, path))
            continue
        result.append(
            DecodeFieldPlan(
                path,
                (field.key, *field.altkeys),
                -1,
                field.required,
                _decode_value(field.type_id, schema),
                prefix + (field.length_field,) if field.length_field else None,
                field.minimum,
                field.maximum,
                field.min_length,
                field.max_length,
            )
        )
    return result


def build_decode_plan(schema: SchemaIR) -> DecodePlan:
    values = tuple(_decode_value(item.id, schema) for item in schema.types)
    objects: list[DecodeObjectPlan] = []
    for record in schema.records:
        fields = _decode_fields(record, schema)
        indexed = tuple(
            DecodeFieldPlan(
                field.path,
                field.keys,
                index,
                field.required,
                field.value,
                field.length_path,
                field.minimum,
                field.maximum,
                field.min_length,
                field.max_length,
            )
            for index, field in enumerate(fields)
        )
        objects.append(
            DecodeObjectPlan(
                record.id,
                indexed,
                tuple(field.seen_index for field in indexed if field.required),
                record.id,
            )
        )
    entries = tuple(
        DecodeEntryPlan(function.name, function.record_id)
        for function in schema.functions
        if function.role == "jsonDecode"
    )
    return DecodePlan(values, tuple(objects), entries)


def _release_operation(field: FieldSchema, schema: SchemaIR) -> ReleaseOperation | None:
    item = schema.type_map()[field.type_id]
    if not field.owns_resources:
        return None
    if item.kind is TypeKind.STRING:
        return ReleaseOperation.STRING
    if item.kind is TypeKind.FIXED_ARRAY:
        return ReleaseOperation.FIXED_ARRAY
    if item.kind is TypeKind.DYNAMIC_ARRAY:
        return ReleaseOperation.DYNAMIC_ARRAY
    if item.kind is TypeKind.RECORD:
        return ReleaseOperation.RECORD
    if item.kind is TypeKind.POINTER:
        return ReleaseOperation.POINTER
    return None


def build_release_plan(schema: SchemaIR) -> ReleasePlan:
    type_map = schema.type_map()
    objects: list[ReleaseObjectPlan] = []
    for record in schema.records:
        fields: list[ReleaseFieldPlan] = []
        for field in record.fields:
            if field.is_length_metadata:
                continue
            operation = _release_operation(field, schema)
            if operation is None:
                continue
            item = type_map[field.type_id]
            fields.append(
                ReleaseFieldPlan(
                    (field.name,),
                    field.type_id,
                    operation,
                    item.target,
                    (field.length_field,) if field.length_field else None,
                    item.capacity,
                )
            )
        objects.append(ReleaseObjectPlan(record.id, tuple(fields), True))
    entries = tuple(
        ReleaseEntryPlan(function.name, function.record_id)
        for function in schema.functions
        if function.role == "jsonCleanup"
    )
    return ReleasePlan(tuple(objects), entries)


def _path(path: tuple[str, ...]) -> str:
    return ".".join(path)


def format_decode_plan(plan: DecodePlan) -> str:
    lines = ["DecodePlan"]
    for obj in plan.objects:
        lines.append(f"  object {obj.record_id} rollback={obj.rollback_record_id}")
        for field in obj.fields:
            flags = [f"seen={field.seen_index}"]
            if field.required:
                flags.append("required")
            if field.value.nullable:
                flags.append("nullable")
            lines.append(
                f"    field {_path(field.path)} keys={field.keys!r} "
                f"op={field.value.operation.value} [{', '.join(flags)}]"
            )
            if field.length_path:
                lines.append(f"      write-length {_path(field.length_path)}")
            constraints = []
            for name, value in (
                ("min", field.minimum),
                ("max", field.maximum),
                ("minlen", field.min_length),
                ("maxlen", field.max_length),
            ):
                if value is not None:
                    constraints.append(f"{name}={value}")
            if constraints:
                lines.append("      constraints " + ", ".join(constraints))
        if obj.required_seen:
            lines.append("    require-seen " + ", ".join(map(str, obj.required_seen)))
    for entry in plan.entries:
        lines.append(f"  entry {entry.function_name} -> {entry.record_id or '?'}")
    return "\n".join(lines)


def format_release_plan(plan: ReleasePlan) -> str:
    lines = ["ReleasePlan"]
    for obj in plan.objects:
        suffix = " clear" if obj.clear_after_release else ""
        lines.append(f"  object {obj.record_id}{suffix}")
        for field in obj.fields:
            line = f"    field {_path(field.path)} op={field.operation.value} type={field.type_id}"
            if field.target_type_id:
                line += f" target={field.target_type_id}"
            lines.append(line)
            if field.length_path:
                lines.append(f"      read-length {_path(field.length_path)}")
    for entry in plan.entries:
        lines.append(f"  entry {entry.function_name} -> {entry.record_id or '?'}")
    return "\n".join(lines)
