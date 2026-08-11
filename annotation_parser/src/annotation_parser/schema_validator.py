from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum

from .annotations import Annotation
from .clang_frontend import TranslationUnit
from .diagnostics import AnnotationError
from .schema import RecordShape, Schema, TypeKind


class _ArgumentMode(Enum):
    FLAG = "flag"
    VALUE = "value"


@dataclass(frozen=True)
class _ArgumentSpec:
    mode: _ArgumentMode
    repeatable: bool = False


_ANNOTATIONS: dict[str, dict[str, _ArgumentSpec]] = {
    "json": {
        "key": _ArgumentSpec(_ArgumentMode.VALUE),
        "altkey": _ArgumentSpec(_ArgumentMode.VALUE, True),
        "required": _ArgumentSpec(_ArgumentMode.FLAG),
        "flatten": _ArgumentSpec(_ArgumentMode.FLAG),
        "type": _ArgumentSpec(_ArgumentMode.VALUE),
        "len": _ArgumentSpec(_ArgumentMode.VALUE),
        "min": _ArgumentSpec(_ArgumentMode.VALUE),
        "max": _ArgumentSpec(_ArgumentMode.VALUE),
        "minlen": _ArgumentSpec(_ArgumentMode.VALUE),
        "maxlen": _ArgumentSpec(_ArgumentMode.VALUE),
        "omitempty": _ArgumentSpec(_ArgumentMode.FLAG),
    },
    "jsonStruct": {
        "asarray": _ArgumentSpec(_ArgumentMode.FLAG),
        "elems": _ArgumentSpec(_ArgumentMode.VALUE),
        "len": _ArgumentSpec(_ArgumentMode.VALUE),
        "cap": _ArgumentSpec(_ArgumentMode.VALUE),
    },
    "jsonDecode": {},
    "jsonCleanup": {},
}


def _validate_annotation(annotation: Annotation) -> None:
    arguments = _ANNOTATIONS.get(annotation.name)
    if arguments is None:
        raise AnnotationError(
            f"unknown annotation @{annotation.name}", annotation.location
        )
    seen: set[str] = set()
    for argument in annotation.arguments:
        spec = arguments.get(argument.name)
        if spec is None:
            raise AnnotationError(
                f"unknown @{annotation.name} argument {argument.name!r}",
                annotation.location,
            )
        if spec.mode is _ArgumentMode.FLAG and argument.value is not None:
            raise AnnotationError(
                f"@{annotation.name} argument {argument.name!r} is a flag",
                annotation.location,
            )
        if spec.mode is _ArgumentMode.VALUE and argument.value is None:
            raise AnnotationError(
                f"@{annotation.name} argument {argument.name!r} requires a value",
                annotation.location,
            )
        if argument.name in seen and not spec.repeatable:
            raise AnnotationError(
                f"duplicate @{annotation.name} argument {argument.name!r}",
                annotation.location,
            )
        seen.add(argument.name)


def validate_annotations(unit: TranslationUnit) -> None:
    annotations: list[Annotation] = []
    for record in unit.records:
        annotations.extend(record.annotations)
        for field in record.fields:
            annotations.extend(field.annotations)
    for function in unit.functions:
        annotations.extend(function.annotations)
    for annotation in annotations:
        _validate_annotation(annotation)


def _validate_constraints(schema: Schema) -> None:
    types = schema.type_map()
    for field in schema.field_map().values():
        item = types[field.type_id]
        if field.minimum is not None or field.maximum is not None:
            if item.kind not in {TypeKind.INTEGER, TypeKind.FLOAT, TypeKind.ENUM}:
                raise AnnotationError("min/max require a numeric field", field.location)
            for value in (field.minimum, field.maximum):
                if value is None:
                    continue
                try:
                    Decimal(value)
                except InvalidOperation as error:
                    raise AnnotationError(
                        "min/max must be numeric", field.location
                    ) from error

        if (
            field.min_length is not None or field.max_length is not None
        ) and item.kind not in {
            TypeKind.STRING,
            TypeKind.FIXED_ARRAY,
            TypeKind.DYNAMIC_ARRAY,
        }:
            raise AnnotationError(
                "minlen/maxlen require a string or array", field.location
            )
        if (
            field.min_length is not None
            and field.max_length is not None
            and field.min_length > field.max_length
        ):
            raise AnnotationError("minlen cannot exceed maxlen", field.location)


def _validate_count_fields(schema: Schema) -> None:
    types = schema.type_map()
    fields = schema.field_map()

    def check(field_id: str, role: str) -> None:
        field = fields[field_id]
        item = types[field.type_id]
        if item.kind is not TypeKind.INTEGER or item.signed:
            raise AnnotationError(
                f"{role} field must be an unsigned integer", field.location
            )

    for field in fields.values():
        if field.length_field_id is not None:
            check(field.length_field_id, "array length")

    for record in schema.records:
        if record.array is None:
            continue
        if record.array.length_field_id is not None:
            check(record.array.length_field_id, "array record len")
        if record.array.capacity_field_id is not None:
            check(record.array.capacity_field_id, "array record cap")


def _validate_bindings(schema: Schema) -> None:
    types = schema.type_map()
    records = schema.record_map()
    fields = schema.field_map()
    metadata = schema.metadata_field_ids()

    for field in fields.values():
        if field.required and field.flatten:
            raise AnnotationError(
                "required cannot be combined with flatten", field.location
            )
        if field.flatten and types[field.type_id].kind is not TypeKind.RECORD:
            raise AnnotationError(
                "flatten requires a by-value structure field", field.location
            )
        if field.flatten and (
            field.key_explicit
            or field.length_field_id is not None
            or any(
                value is not None
                for value in (
                    field.minimum,
                    field.maximum,
                    field.min_length,
                    field.max_length,
                )
            )
        ):
            raise AnnotationError(
                "flatten cannot be combined with key, len, or constraints",
                field.location,
            )
        if field.id in metadata and field.required:
            raise AnnotationError(
                "an array length metadata field cannot be required", field.location
            )
        if field.flatten and records[field.type_id].shape is RecordShape.ARRAY:
            raise AnnotationError(
                "an array-shaped record cannot be flattened", field.location
            )

    def add_record(record_id: str, keys: dict[str, str], prefix: str) -> None:
        for field in records[record_id].fields:
            if field.id in metadata or field.ignored:
                continue
            if field.flatten:
                add_record(field.type_id, keys, prefix + field.name + ".")
                continue
            for key in (field.key, *field.altkeys):
                previous = keys.get(key)
                if previous is not None:
                    raise AnnotationError(
                        f"JSON key {key!r} is shared by "
                        f"{previous} and {prefix + field.name}",
                        field.location,
                    )
                keys[key] = prefix + field.name

    for record in records.values():
        if record.shape is RecordShape.OBJECT:
            add_record(record.id, {}, "")


def _validate_ownership(schema: Schema) -> None:
    types = schema.type_map()
    for record in schema.records:
        if (
            record.array is not None
            and record.array.length_field_id is None
            and record.array.capacity_field_id is None
            and types[record.array.element_type_id].owns_resources
        ):
            raise AnnotationError(
                "an array record without len or cap requires a trivially "
                "releasable element type",
                record.location,
            )


def validate_schema(schema: Schema) -> None:
    _validate_constraints(schema)
    _validate_count_fields(schema)
    _validate_bindings(schema)
    _validate_ownership(schema)
