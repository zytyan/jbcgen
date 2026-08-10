from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Mapping

from ..annotations import Annotation
from ..clang_frontend import AstField
from ..diagnostics import AnnotationError
from ..schema_core import CoreTypeKind
from .base import (
    AnnotationCommandSpec,
    PluginBuildContext,
    PluginKey,
    SchemaPluginBase,
    argument_value,
    find_annotation,
    flag_argument,
    frozen_map,
    has_flag,
    value_argument,
)
from .builtin import ARRAY_LAYOUT_KEY


class JsonValueKind(Enum):
    BOOL = "bool"
    INTEGER = "integer"
    FLOAT = "float"
    ENUM = "enum"
    STRING = "string"
    FIXED_ARRAY = "fixed_array"
    POINTER = "pointer"
    DYNAMIC_ARRAY = "dynamic_array"
    RECORD = "record"


class RecordShape(Enum):
    OBJECT = "object"
    ARRAY = "array"


@dataclass(frozen=True)
class JsonValueType:
    id: str
    kind: JsonValueKind
    c_type: str
    bits: int | None = None
    signed: bool | None = None
    target: str | None = None
    capacity: int | None = None


@dataclass(frozen=True)
class JsonValueTypesState:
    types: Mapping[str, JsonValueType]
    core_types: Mapping[str, str]
    fields: Mapping[str, str]
    records: Mapping[str, RecordShape]


VALUE_TYPES_KEY = PluginKey("jbcgen.json.value-types.v1", JsonValueTypesState)


class JsonValueTypesPlugin(SchemaPluginBase[JsonValueTypesState]):
    key = VALUE_TYPES_KEY
    dependencies = (ARRAY_LAYOUT_KEY,)

    def build(self, context: PluginBuildContext) -> JsonValueTypesState:
        core = context.core
        assert core is not None
        plugins = context.states
        arrays = plugins.require(ARRAY_LAYOUT_KEY)
        core_types = core.type_map()
        result: dict[str, JsonValueType] = {}
        derived: dict[str, str] = {}

        def convert(core_type_id: str) -> str:
            if core_type_id in derived:
                return derived[core_type_id]
            item = core_types[core_type_id]
            if item.kind is CoreTypeKind.BOOL:
                value = JsonValueType("bool", JsonValueKind.BOOL, item.c_type, 8, False)
            elif item.kind is CoreTypeKind.INTEGER:
                value = JsonValueType(
                    item.id, JsonValueKind.INTEGER, item.c_type, item.bits, item.signed
                )
            elif item.kind is CoreTypeKind.FLOAT:
                value = JsonValueType(
                    item.id, JsonValueKind.FLOAT, item.c_type, item.bits, True
                )
            elif item.kind is CoreTypeKind.ENUM:
                value = JsonValueType(
                    item.id, JsonValueKind.ENUM, item.c_type, item.bits, item.signed
                )
            elif item.kind is CoreTypeKind.RECORD:
                value = JsonValueType(item.id, JsonValueKind.RECORD, item.c_type)
            elif item.kind in {CoreTypeKind.POINTER, CoreTypeKind.FIXED_ARRAY}:
                if item.target is None:
                    raise AnnotationError(f"incomplete C type {item.c_type!r}")
                target = core_types[item.target]
                is_char = (
                    target.kind is CoreTypeKind.INTEGER
                    and target.name in {"char", "signed char", "unsigned char"}
                )
                if is_char:
                    if item.kind is CoreTypeKind.POINTER:
                        value = JsonValueType(
                            "string:pointer", JsonValueKind.STRING, item.c_type
                        )
                    else:
                        if item.capacity is None or item.capacity <= 0:
                            raise AnnotationError(
                                "zero-length and flexible C arrays are not supported"
                            )
                        value = JsonValueType(
                            f"string:fixed:{item.capacity}",
                            JsonValueKind.STRING,
                            item.c_type,
                            capacity=item.capacity,
                        )
                else:
                    target_id = convert(item.target)
                    if item.kind is CoreTypeKind.POINTER:
                        value = JsonValueType(
                            f"pointer:{target_id}",
                            JsonValueKind.POINTER,
                            item.c_type,
                            target=target_id,
                        )
                    else:
                        if item.capacity is None or item.capacity <= 0:
                            raise AnnotationError(
                                "zero-length and flexible C arrays are not supported"
                            )
                        value = JsonValueType(
                            f"fixed-array:{item.capacity}:{target_id}",
                            JsonValueKind.FIXED_ARRAY,
                            item.c_type,
                            target=target_id,
                            capacity=item.capacity,
                        )
            else:
                raise AnnotationError(f"unsupported C type {item.c_type!r}")
            result.setdefault(value.id, value)
            derived[core_type_id] = value.id
            return value.id

        field_arrays = arrays.fields
        fields: dict[str, str] = {}
        for record in core.records:
            for field in record.fields:
                layout = field_arrays.get(field.id)
                if layout and layout.dynamic:
                    pointer = core_types[field.type_id]
                    assert pointer.target is not None
                    target_id = convert(pointer.target)
                    value = JsonValueType(
                        f"dynamic-array:{target_id}",
                        JsonValueKind.DYNAMIC_ARRAY,
                        field.c_type,
                        target=target_id,
                    )
                    result.setdefault(value.id, value)
                    type_id = value.id
                else:
                    type_id = convert(field.type_id)
                fields[field.id] = type_id
        records = {
            record.id: (
                RecordShape.ARRAY
                if record.id in arrays.records
                else RecordShape.OBJECT
            )
            for record in core.records
        }
        return JsonValueTypesState(
            frozen_map(result.items()),
            frozen_map(derived.items()),
            frozen_map(fields.items()),
            frozen_map(records.items()),
        )

    def format_state(self, state: JsonValueTypesState) -> str:
        lines = [
            f"type {item.id} kind={item.kind.value}"
            + (f" target={item.target}" if item.target else "")
            + (f" capacity={item.capacity}" if item.capacity is not None else "")
            for item in state.types.values()
        ]
        lines.extend(
            f"field {field_id} -> {type_id}"
            for field_id, type_id in state.fields.items()
        )
        lines.extend(
            f"record {record_id} shape={shape.value}"
            for record_id, shape in state.records.items()
        )
        return "\n".join(lines)


@dataclass(frozen=True)
class FieldConstraint:
    minimum: str | None
    maximum: str | None
    min_length: int | None
    max_length: int | None


@dataclass(frozen=True)
class ConstraintsState:
    fields: Mapping[str, FieldConstraint]


CONSTRAINTS_KEY = PluginKey("jbcgen.json.constraints.v1", ConstraintsState)


class ConstraintsPlugin(SchemaPluginBase[ConstraintsState]):
    key = CONSTRAINTS_KEY
    annotation_commands = (
        AnnotationCommandSpec(
            "json",
            tuple(
                value_argument(name)
                for name in ("min", "max", "minlen", "maxlen")
            ),
        ),
    )
    dependencies = (VALUE_TYPES_KEY,)

    def build(self, context: PluginBuildContext) -> ConstraintsState:
        unit = context.unit
        core = context.core
        assert core is not None
        plugins = context.states
        values = plugins.require(VALUE_TYPES_KEY)
        field_types = values.fields
        types = values.types
        core_fields = core.field_map()
        ast_fields = {
            f"field:{record.name}.{field.name}": field
            for record in unit.records
            for field in record.fields
            if f"field:{record.name}.{field.name}" in core_fields
        }
        result: dict[str, FieldConstraint] = {}
        for field_id, ast_field in ast_fields.items():
            annotation = find_annotation(ast_field.annotations, "json", ast_field.location)
            minimum = argument_value(annotation, "min")
            maximum = argument_value(annotation, "max")
            if minimum is not None or maximum is not None:
                if types[field_types[field_id]].kind not in {
                    JsonValueKind.INTEGER,
                    JsonValueKind.FLOAT,
                    JsonValueKind.ENUM,
                }:
                    raise AnnotationError("min/max require a numeric field", ast_field.location)
                for value in (minimum, maximum):
                    if value is not None:
                        try:
                            Decimal(value)
                        except InvalidOperation as error:
                            raise AnnotationError("min/max must be numeric", ast_field.location) from error
            min_length = self._length(annotation, "minlen", ast_field)
            max_length = self._length(annotation, "maxlen", ast_field)
            if min_length is not None or max_length is not None:
                if types[field_types[field_id]].kind not in {
                    JsonValueKind.STRING,
                    JsonValueKind.FIXED_ARRAY,
                    JsonValueKind.DYNAMIC_ARRAY,
                }:
                    raise AnnotationError(
                        "minlen/maxlen require a string or array", ast_field.location
                    )
            if min_length is not None and max_length is not None and min_length > max_length:
                raise AnnotationError("minlen cannot exceed maxlen", ast_field.location)
            if any(value is not None for value in (minimum, maximum, min_length, max_length)):
                result[field_id] = FieldConstraint(
                    minimum, maximum, min_length, max_length
                )
        return ConstraintsState(frozen_map(result.items()))

    def _length(
        self, annotation: Annotation | None, name: str, field: AstField
    ) -> int | None:
        value = argument_value(annotation, name)
        if value is None:
            return None
        try:
            result = int(value, 10)
        except ValueError as error:
            raise AnnotationError(f"{name} must be a non-negative integer", field.location) from error
        if result < 0:
            raise AnnotationError(f"{name} must be a non-negative integer", field.location)
        return result

    def format_state(self, state: ConstraintsState) -> str:
        return "\n".join(
            f"{field_id} min={item.minimum} max={item.maximum} "
            f"minlen={item.min_length} maxlen={item.max_length}"
            for field_id, item in state.fields.items()
        )


@dataclass(frozen=True)
class OwnershipState:
    types: Mapping[str, bool]
    fields: Mapping[str, bool]
    records: Mapping[str, bool]


OWNERSHIP_KEY = PluginKey("jbcgen.json.ownership.v1", OwnershipState)


class OwnershipPlugin(SchemaPluginBase[OwnershipState]):
    key = OWNERSHIP_KEY
    dependencies = (VALUE_TYPES_KEY, ARRAY_LAYOUT_KEY)

    def build(self, context: PluginBuildContext) -> OwnershipState:
        core = context.core
        assert core is not None
        plugins = context.states
        values = plugins.require(VALUE_TYPES_KEY)
        arrays = plugins.require(ARRAY_LAYOUT_KEY)
        types = values.types
        field_types = values.fields
        array_records = arrays.records
        ignored = {
            field_id
            for item in arrays.records.values()
            for field_id in item.ignored_field_ids
        }
        metadata = arrays.metadata_field_ids()
        record_ownership = {record.id: record.id in array_records for record in core.records}

        def owns(type_id: str) -> bool:
            item = types[type_id]
            if item.kind in {
                JsonValueKind.POINTER,
                JsonValueKind.DYNAMIC_ARRAY,
            }:
                return True
            if item.kind is JsonValueKind.STRING:
                return item.capacity is None
            if item.kind is JsonValueKind.FIXED_ARRAY and item.target:
                return owns(item.target)
            if item.kind is JsonValueKind.RECORD:
                return record_ownership.get(item.id, False)
            return False

        changed = True
        while changed:
            changed = False
            for record in core.records:
                value = record.id in array_records or any(
                    owns(field_types[field.id])
                    for field in record.fields
                    if field.id not in ignored and field.id not in metadata
                )
                if value != record_ownership[record.id]:
                    record_ownership[record.id] = value
                    changed = True

        type_ownership = {type_id: owns(type_id) for type_id in values.types}
        fields = {
            field.id: (
                False
                if field.id in ignored or field.id in metadata
                else owns(field_types[field.id])
            )
            for record in core.records
            for field in record.fields
        }
        for record_id, layout in arrays.records.items():
            if (
                layout.length_field_id is None
                and layout.capacity_field_id is None
                and owns(values.core_types[layout.element_type_id])
            ):
                raise AnnotationError(
                    "an array record without len or cap requires a trivially releasable element type",
                    core.record_map()[record_id].location,
                )
        return OwnershipState(
            frozen_map(type_ownership.items()),
            frozen_map(fields.items()),
            frozen_map(record_ownership.items()),
        )

    def format_state(self, state: OwnershipState) -> str:
        lines = [
            f"record {record_id} owns={str(owns).lower()}"
            for record_id, owns in state.records.items()
        ]
        lines.extend(
            f"field {field_id} owns={str(owns).lower()}"
            for field_id, owns in state.fields.items()
        )
        return "\n".join(lines)


@dataclass(frozen=True)
class EncodeHintsState:
    omitempty_field_ids: tuple[str, ...]


ENCODE_HINTS_KEY = PluginKey("jbcgen.json.encode-hints.v1", EncodeHintsState)


class EncodeHintsPlugin(SchemaPluginBase[EncodeHintsState]):
    key = ENCODE_HINTS_KEY
    annotation_commands = (
        AnnotationCommandSpec("json", (flag_argument("omitempty"),)),
    )

    def build(self, context: PluginBuildContext) -> EncodeHintsState:
        unit = context.unit
        core = context.core
        assert core is not None
        reachable = core.field_map()
        fields = []
        for record in unit.records:
            for field in record.fields:
                field_id = f"field:{record.name}.{field.name}"
                if field_id not in reachable:
                    continue
                annotation = find_annotation(field.annotations, "json", field.location)
                if has_flag(annotation, "omitempty"):
                    fields.append(field_id)
        return EncodeHintsState(tuple(sorted(fields)))

    def format_state(self, state: EncodeHintsState) -> str:
        return "\n".join(f"omitempty {item}" for item in state.omitempty_field_ids)
