from __future__ import annotations

import re
from dataclasses import dataclass

from .schema import RecordShape, Schema, TypeKind

_RUNTIME_TYPE_DESCRIPTORS = {
    "bool": "json_reflect_type_bool",
    "integer:i8": "json_reflect_type_i8",
    "integer:i16": "json_reflect_type_i16",
    "integer:i32": "json_reflect_type_i32",
    "integer:i64": "json_reflect_type_i64",
    "integer:u8": "json_reflect_type_u8",
    "integer:u16": "json_reflect_type_u16",
    "integer:u32": "json_reflect_type_u32",
    "integer:u64": "json_reflect_type_u64",
    "float:32": "json_reflect_type_f32",
    "float:64": "json_reflect_type_f64",
}


def _identifier(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", value)


def _descriptor_name(prefix: str, value: str) -> str:
    return f"jbc_{prefix}_{_identifier(value.removeprefix('record:'))}"


@dataclass(frozen=True)
class TypeDescriptorPlan:
    type_id: str
    symbol: str
    runtime: bool


@dataclass(frozen=True)
class KeyEntryPlan:
    key: str
    field_index: int


@dataclass(frozen=True)
class FieldPlan:
    field_id: str
    path: tuple[str, ...]
    length_path: tuple[str, ...] | None
    field_index: int


@dataclass(frozen=True)
class TypePlan:
    record_id: str
    shape: RecordShape
    type_descriptor: str
    record_descriptor: str
    fields: tuple[FieldPlan, ...]
    key_entries: tuple[KeyEntryPlan, ...]
    owned_field_ids: tuple[str, ...]
    dependencies: tuple[str, ...]


@dataclass(frozen=True)
class GeneratePlan:
    descriptors: tuple[TypeDescriptorPlan, ...]
    types: tuple[TypePlan, ...]

    def type_map(self) -> dict[str, TypePlan]:
        return {item.record_id: item for item in self.types}

    def descriptor_map(self) -> dict[str, str]:
        return {item.type_id: item.symbol for item in self.descriptors}


class GeneratePlanBuilder:
    def __init__(self, schema: Schema):
        self.schema = schema
        self.types = schema.type_map()
        self.records = schema.record_map()
        self.fields = schema.field_map()
        self.metadata = schema.metadata_field_ids()

    def build(self) -> GeneratePlan:
        used = self._used_type_ids()
        descriptors = tuple(
            TypeDescriptorPlan(
                item.id,
                _RUNTIME_TYPE_DESCRIPTORS.get(
                    item.id, _descriptor_name("type", item.id)
                ),
                item.id in _RUNTIME_TYPE_DESCRIPTORS,
            )
            for item in self.schema.types
            if item.id in used
        )
        return GeneratePlan(
            descriptors,
            tuple(self._type_plan(record.id) for record in self.schema.records),
        )

    def _used_type_ids(self) -> set[str]:
        used = {record.id for record in self.schema.records}
        roots: set[str] = set()
        for record in self.schema.records:
            if record.array is not None:
                roots.add(record.array.element_type_id)
                for field_id in (
                    record.array.length_field_id,
                    record.array.capacity_field_id,
                ):
                    if field_id:
                        roots.add(self.fields[field_id].type_id)
            else:
                for field in record.fields:
                    if not field.ignored and field.id not in self.metadata:
                        roots.add(field.type_id)
                    if field.length_field_id:
                        roots.add(self.fields[field.length_field_id].type_id)

        def visit(type_id: str) -> None:
            if type_id in used:
                return
            used.add(type_id)
            target = self.types[type_id].target
            if target is not None:
                visit(target)

        for type_id in roots:
            visit(type_id)
        return used

    def _type_plan(self, record_id: str) -> TypePlan:
        record = self.records[record_id]
        fields = (
            () if record.shape is RecordShape.ARRAY else self._object_fields(record_id)
        )
        keys = tuple(
            sorted(
                (
                    KeyEntryPlan(key, field.field_index)
                    for field in fields
                    for key in (
                        self.fields[field.field_id].key,
                        *self.fields[field.field_id].altkeys,
                    )
                ),
                key=lambda item: (
                    len(item.key.encode("utf-8")),
                    item.key.encode("utf-8"),
                ),
            )
        )
        owned = tuple(
            field.id
            for field in record.fields
            if field.owns_resources
            and not field.ignored
            and field.id not in self.metadata
        )
        return TypePlan(
            record_id,
            record.shape,
            _descriptor_name("type", record_id),
            _descriptor_name("record", record_id),
            fields,
            keys,
            owned,
            self._dependencies(record_id),
        )

    def _object_fields(
        self,
        owner_record_id: str,
        record_id: str | None = None,
        prefix: tuple[str, ...] = (),
    ) -> tuple[FieldPlan, ...]:
        record_id = record_id or owner_record_id
        result: list[FieldPlan] = []
        for field in self.records[record_id].fields:
            if field.id in self.metadata or field.ignored:
                continue
            path = prefix + (field.name,)
            if field.flatten:
                result.extend(self._object_fields(owner_record_id, field.type_id, path))
                continue
            length = (
                self.fields[field.length_field_id] if field.length_field_id else None
            )
            result.append(
                FieldPlan(
                    field.id,
                    path,
                    prefix + (length.name,) if length else None,
                    len(result),
                )
            )
        return tuple(
            FieldPlan(item.field_id, item.path, item.length_path, index)
            for index, item in enumerate(result)
        )

    def _dependencies(self, record_id: str) -> tuple[str, ...]:
        record = self.records[record_id]
        type_ids = (
            (record.array.element_type_id,)
            if record.array is not None
            else tuple(field.type_id for field in record.fields if not field.ignored)
        )
        dependencies: set[str] = set()

        def visit(type_id: str, seen: set[str]) -> None:
            if type_id in seen:
                return
            seen.add(type_id)
            item = self.types[type_id]
            if item.kind is TypeKind.RECORD:
                if item.id != record_id:
                    dependencies.add(item.id)
                return
            if item.target is not None:
                visit(item.target, seen)

        for type_id in type_ids:
            visit(type_id, set())
        return tuple(sorted(dependencies))


def build_generate_plan(schema: Schema) -> GeneratePlan:
    return GeneratePlanBuilder(schema).build()


def format_generate_plan(plan: GeneratePlan, schema: Schema) -> str:
    fields = schema.field_map()
    records = schema.record_map()
    lines = ["GeneratePlan", "  descriptors"]
    for descriptor in plan.descriptors:
        suffix = " [runtime]" if descriptor.runtime else ""
        lines.append(f"    {descriptor.type_id} -> {descriptor.symbol}{suffix}")
    for item in plan.types:
        lines.append(
            f"  type {item.record_id} shape={item.shape.value} "
            f"descriptor={item.type_descriptor} record={item.record_descriptor}"
        )
        lines.append("    decode-failure -> json_reflect_release(self)")
        if item.dependencies:
            lines.append(f"    dependencies {item.dependencies!r}")
        if item.shape is RecordShape.ARRAY:
            layout = records[item.record_id].array
            assert layout is not None
            parts = [
                f"elems={layout.elems_field_id}",
                f"element={layout.element_type_id}",
            ]
            if layout.length_field_id:
                parts.append(f"write-length={layout.length_field_id}")
            if layout.capacity_field_id:
                parts.append(f"write-capacity={layout.capacity_field_id}")
            lines.append("    array " + " ".join(parts))
        for field in item.fields:
            schema_field = fields[field.field_id]
            flags = [f"index={field.field_index}"]
            if schema_field.required:
                flags.append("required")
            lines.append(
                f"    field {'.'.join(field.path)} type={schema_field.type_id} "
                f"keys={(schema_field.key, *schema_field.altkeys)!r} "
                f"[{' '.join(flags)}]"
            )
            if field.length_path:
                lines.append(f"      length {'.'.join(field.length_path)}")
        if item.owned_field_ids:
            lines.append(f"    release-storage {item.owned_field_ids!r}")
        if item.key_entries:
            lines.append(
                "    key-order "
                + repr(
                    tuple((entry.key, entry.field_index) for entry in item.key_entries)
                )
            )
    return "\n".join(lines)
