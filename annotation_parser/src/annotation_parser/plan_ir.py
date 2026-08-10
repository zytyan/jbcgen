from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .schema_core import CoreFieldSchema, CoreRecordSchema
from .schema_ir import RecordShape, SchemaIR, TypeKind
from .schema_plugins import (
    ARRAY_LAYOUT_KEY,
    BINDING_KEY,
    CONSTRAINTS_KEY,
    ENTRYPOINTS_KEY,
    OWNERSHIP_KEY,
    VALUE_TYPES_KEY,
)


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
    length_type_id: str | None = None


@dataclass(frozen=True)
class DecodeObjectPlan:
    record_id: str
    fields: tuple[DecodeFieldPlan, ...]
    required_seen: tuple[int, ...]
    rollback_record_id: str


@dataclass(frozen=True)
class DecodeArrayPlan:
    record_id: str
    elems_path: tuple[str, ...]
    element: DecodeValuePlan
    length_path: tuple[str, ...] | None
    length_type_id: str | None
    capacity_path: tuple[str, ...] | None
    capacity_type_id: str | None
    rollback_record_id: str


@dataclass(frozen=True)
class DecodeEntryPlan:
    function_name: str
    record_id: str | None


@dataclass(frozen=True)
class DecodePlan:
    values: tuple[DecodeValuePlan, ...]
    objects: tuple[DecodeObjectPlan, ...]
    arrays: tuple[DecodeArrayPlan, ...]
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
class ReleaseArrayPlan:
    record_id: str
    elems_path: tuple[str, ...]
    element_type_id: str
    length_path: tuple[str, ...] | None
    capacity_path: tuple[str, ...] | None
    release_elements: bool
    clear_after_release: bool


@dataclass(frozen=True)
class ReleaseEntryPlan:
    function_name: str
    record_id: str | None


@dataclass(frozen=True)
class ReleasePlan:
    objects: tuple[ReleaseObjectPlan, ...]
    arrays: tuple[ReleaseArrayPlan, ...]
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
    item = schema.plugins.require(VALUE_TYPES_KEY).type_map()[type_id]
    return DecodeValuePlan(
        type_id,
        _DECODE_OPERATIONS[item.kind],
        item.target,
        item.kind in {TypeKind.STRING, TypeKind.DYNAMIC_ARRAY, TypeKind.POINTER} and item.capacity is None,
        item.capacity,
    )


def _decode_fields(
    record: CoreRecordSchema,
    schema: SchemaIR,
    prefix: tuple[str, ...] = (),
) -> list[DecodeFieldPlan]:
    records = schema.core.record_map()
    bindings = schema.plugins.require(BINDING_KEY).field_map()
    arrays = schema.plugins.require(ARRAY_LAYOUT_KEY)
    array_fields = arrays.field_map()
    metadata = arrays.metadata_field_ids()
    field_types = schema.plugins.require(VALUE_TYPES_KEY).field_map()
    constraints = schema.plugins.require(CONSTRAINTS_KEY).field_map()
    core_fields = schema.core.field_map()
    result: list[DecodeFieldPlan] = []
    for field in record.fields:
        if field.id in metadata:
            continue
        binding = bindings[field.id]
        path = prefix + (field.name,)
        if binding.flatten:
            nested = records[field.type_id]
            result.extend(_decode_fields(nested, schema, path))
            continue
        layout = array_fields.get(field.id)
        constraint = constraints.get(field.id)
        length_field = core_fields[layout.length_field_id] if layout else None
        result.append(
            DecodeFieldPlan(
                path,
                (binding.key, *binding.altkeys),
                -1,
                binding.required,
                _decode_value(field_types[field.id], schema),
                prefix + (length_field.name,) if length_field else None,
                constraint.minimum if constraint else None,
                constraint.maximum if constraint else None,
                constraint.min_length if constraint else None,
                constraint.max_length if constraint else None,
                field_types[length_field.id] if length_field else None,
            )
        )
    return result


def build_decode_plan(schema: SchemaIR) -> DecodePlan:
    value_state = schema.plugins.require(VALUE_TYPES_KEY)
    values = tuple(_decode_value(item.id, schema) for item in value_state.types)
    arrays_state = schema.plugins.require(ARRAY_LAYOUT_KEY)
    array_records = arrays_state.record_map()
    field_types = value_state.field_map()
    core_fields = schema.core.field_map()
    objects: list[DecodeObjectPlan] = []
    arrays: list[DecodeArrayPlan] = []
    for record in schema.core.records:
        storage = array_records.get(record.id)
        if storage is not None:
            elems = core_fields[storage.elems_field_id]
            length = core_fields[storage.length_field_id] if storage.length_field_id else None
            capacity = core_fields[storage.capacity_field_id] if storage.capacity_field_id else None
            arrays.append(
                DecodeArrayPlan(
                    record.id,
                    (elems.name,),
                    _decode_value(value_state.core_type_map()[storage.element_type_id], schema),
                    (length.name,) if length else None,
                    field_types[length.id] if length else None,
                    (capacity.name,) if capacity else None,
                    field_types[capacity.id] if capacity else None,
                    record.id,
                )
            )
            continue
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
                field.length_type_id,
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
        DecodeEntryPlan(item.function_id.removeprefix("function:"), item.record_id)
        for item in schema.plugins.require(ENTRYPOINTS_KEY).functions
        if item.role == "jsonDecode"
    )
    return DecodePlan(values, tuple(objects), tuple(arrays), entries)


def _release_operation(field: CoreFieldSchema, schema: SchemaIR) -> ReleaseOperation | None:
    type_id = schema.plugins.require(VALUE_TYPES_KEY).field_map()[field.id]
    item = schema.plugins.require(VALUE_TYPES_KEY).type_map()[type_id]
    if not schema.plugins.require(OWNERSHIP_KEY).field_map()[field.id]:
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
    values = schema.plugins.require(VALUE_TYPES_KEY)
    type_map = values.type_map()
    field_types = values.field_map()
    layouts = schema.plugins.require(ARRAY_LAYOUT_KEY)
    array_records = layouts.record_map()
    metadata = layouts.metadata_field_ids()
    ownership = schema.plugins.require(OWNERSHIP_KEY)
    core_fields = schema.core.field_map()
    objects: list[ReleaseObjectPlan] = []
    arrays: list[ReleaseArrayPlan] = []
    for record in schema.core.records:
        storage = array_records.get(record.id)
        if storage is not None:
            elems = core_fields[storage.elems_field_id]
            length = core_fields[storage.length_field_id] if storage.length_field_id else None
            capacity = core_fields[storage.capacity_field_id] if storage.capacity_field_id else None
            element_type_id = values.core_type_map()[storage.element_type_id]
            arrays.append(
                ReleaseArrayPlan(
                    record.id,
                    (elems.name,),
                    element_type_id,
                    (length.name,) if length else None,
                    (capacity.name,) if capacity else None,
                    ownership.type_map()[element_type_id],
                    True,
                )
            )
            continue
        fields: list[ReleaseFieldPlan] = []
        for field in record.fields:
            if field.id in metadata:
                continue
            operation = _release_operation(field, schema)
            if operation is None:
                continue
            type_id = field_types[field.id]
            item = type_map[type_id]
            layout = layouts.field_map().get(field.id)
            length = core_fields[layout.length_field_id] if layout else None
            fields.append(
                ReleaseFieldPlan(
                    (field.name,),
                    type_id,
                    operation,
                    item.target,
                    (length.name,) if length else None,
                    item.capacity,
                )
            )
        objects.append(ReleaseObjectPlan(record.id, tuple(fields), True))
    entries = tuple(
        ReleaseEntryPlan(item.function_id.removeprefix("function:"), item.record_id)
        for item in schema.plugins.require(ENTRYPOINTS_KEY).functions
        if item.role == "jsonCleanup"
    )
    return ReleasePlan(tuple(objects), tuple(arrays), entries)


def _type_owns(type_id: str, schema: SchemaIR) -> bool:
    return schema.plugins.require(OWNERSHIP_KEY).type_map()[type_id]


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
    for array in plan.arrays:
        lines.append(f"  array record {array.record_id} rollback={array.rollback_record_id}")
        lines.append(
            f"    elems {_path(array.elems_path)} element={array.element.type_id} "
            f"op={array.element.operation.value} delayed-allocation"
        )
        if array.length_path:
            lines.append(
                f"    write-length {_path(array.length_path)} type={array.length_type_id}"
            )
        if array.capacity_path:
            lines.append(
                f"    write-capacity {_path(array.capacity_path)} type={array.capacity_type_id}"
            )
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
    for array in plan.arrays:
        source = (
            f"len:{_path(array.length_path)}"
            if array.length_path
            else f"cap:{_path(array.capacity_path)}"
            if array.capacity_path
            else "trivial-only"
        )
        behavior = "release-elements" if array.release_elements else "free-buffer"
        lines.append(f"  array record {array.record_id} clear count={source} {behavior}")
        lines.append(
            f"    elems {_path(array.elems_path)} element={array.element_type_id}"
        )
    for entry in plan.entries:
        lines.append(f"  entry {entry.function_name} -> {entry.record_id or '?'}")
    return "\n".join(lines)
