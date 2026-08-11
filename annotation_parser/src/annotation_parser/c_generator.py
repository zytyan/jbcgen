from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

from . import c_templates as templates
from .clang_frontend import BasicType
from .generate_plan import GeneratePlan, TypePlan
from .schema import FieldSchema, RecordSchema, RecordShape, Schema, TypeKind, TypeSchema


def _c_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=True)


def _c_slice(value: str) -> str:
    literal = _c_string(value)
    return f"{{{literal}, sizeof({literal}) - 1}}"


def _array_size(name: str) -> str:
    return f"sizeof({name}) / sizeof({name}[0])"


def _comment_text(value: str) -> str:
    return value.replace("\r", r"\r").replace("\n", r"\n").replace("*/", "* /")


@dataclass(frozen=True)
class _Bounds:
    flags: tuple[str, ...]
    minimum: str
    maximum: str


class CGenerator:
    def __init__(self, schema: Schema, plan: GeneratePlan):
        self.schema = schema
        self.types = schema.type_map()
        self.records = schema.record_map()
        self.fields = schema.field_map()
        self.type_plans = plan.type_map()
        self.descriptors = plan.descriptor_map()

    def generate(self, include: str, source_header: str, source_sha256: str) -> str:
        forward = templates.render_c_template(
            templates.FORWARD_DECLARATIONS,
            type_declarations="\n".join(
                f"static const json_reflect_type {symbol};"
                for symbol in self.descriptors.values()
            ),
            record_declarations="\n".join(
                f"static const json_reflect_record {item.record_descriptor};"
                for item in self.type_plans.values()
            ),
        )
        record_blocks = "\n\n".join(
            self._record_block(record) for record in self.schema.records
        )
        non_record_types = "\n\n".join(
            self._type_definition(item)
            for item in self.schema.types
            if item.kind is not TypeKind.RECORD and item.id in self.descriptors
        )
        descriptors = "\n\n".join(
            part for part in (non_record_types, record_blocks) if part
        )
        public_functions = self._public_functions()
        return (
            templates.render_c_template(
                templates.C_FILE,
                include=_c_string(include),
                source_header=_comment_text(source_header),
                source_sha256=source_sha256,
                forward_declarations=forward,
                descriptors=descriptors,
                public_functions=public_functions,
            ).rstrip()
            + "\n"
        )

    def _kind(self, item: TypeSchema) -> str:
        return {
            TypeKind.BOOL: "JSON_REFLECT_BOOL",
            TypeKind.INTEGER: "JSON_REFLECT_INTEGER",
            TypeKind.FLOAT: "JSON_REFLECT_FLOAT",
            TypeKind.ENUM: "JSON_REFLECT_ENUM",
            TypeKind.STRING: "JSON_REFLECT_STRING",
            TypeKind.FIXED_ARRAY: "JSON_REFLECT_FIXED_ARRAY",
            TypeKind.DYNAMIC_ARRAY: "JSON_REFLECT_DYNAMIC_ARRAY",
            TypeKind.RECORD: "JSON_REFLECT_RECORD",
            TypeKind.POINTER: "JSON_REFLECT_POINTER",
        }[item.kind]

    def _basic_id(self, item: TypeSchema) -> str:
        if item.basic_type is None:
            return "JSON_REFLECT_BASIC_ID_NONE"
        return f"JSON_REFLECT_BASIC_ID_{item.basic_type.name}"

    def _basic_type_pointer(self, basic_type: BasicType) -> str:
        return f"&json_reflect_type_{basic_type.value.replace('-', '_')}"

    def _schema_type_pointer(self, type_id: str) -> str:
        item = self.types[type_id]
        if item.basic_type is not None and item.kind is not TypeKind.ENUM:
            return self._basic_type_pointer(item.basic_type)
        return f"&{self.descriptors[type_id]}"

    def _type_definition(self, item: TypeSchema) -> str:
        if item.kind in {TypeKind.BOOL, TypeKind.INTEGER, TypeKind.FLOAT}:
            raise ValueError(f"basic type {item.id} must use its runtime descriptor")
        target = self._schema_type_pointer(item.target) if item.target else "NULL"
        record = (
            f"&{self.type_plans[item.id].record_descriptor}"
            if item.kind is TypeKind.RECORD
            else "NULL"
        )
        bits = str(item.bits or 0)
        flags = "JSON_REFLECT_SIGNED" if item.signed else "0"
        basic_id = self._basic_id(item)
        if item.kind is TypeKind.ENUM:
            expression = f"({item.c_type}){{0}}"
            basic_id = f"JSON_REFLECT_BASIC_ID({expression})"
            bits = f"sizeof({item.c_type}) * CHAR_BIT"
            flags = f"JSON_REFLECT_BASIC_SIGNED({expression})"
        return "\n".join(
            (
                f"static const json_reflect_type {self.descriptors[item.id]} = {{",
                f"    .kind = {self._kind(item)},",
                f"    .basic_id = {basic_id},",
                f"    .bits = {bits},",
                f"    .flags = {flags},",
                f"    .size = sizeof({item.c_type}),",
                f"    .capacity = {item.capacity or 0},",
                f"    .target = {target},",
                f"    .record = {record},",
                "};",
            )
        )

    def _field_expression(self, record: RecordSchema, path: tuple[str, ...]) -> str:
        return f"(({record.c_type} *)0)->{'.'.join(path)}"

    def _type_pointer(self, type_id: str, expression: str) -> str:
        item = self.types[type_id]
        if item.kind in {TypeKind.BOOL, TypeKind.INTEGER, TypeKind.FLOAT}:
            return f"JSON_REFLECT_BASIC_TYPE({expression})"
        return self._schema_type_pointer(type_id)

    def _record_block(self, record: RecordSchema) -> str:
        plan = self.type_plans[record.id]
        constraints, constraint_names = self._constraints(record, plan)
        keys = self._keys(plan)
        fields = self._field_descriptors(record, plan, constraint_names)
        storage = self._storage(record, plan)
        array_layout = self._array_layout(record, plan)
        record_definition = self._record_definition(record, plan)
        type_definition = self._type_definition(self.types[record.id])
        return templates.render_c_template(
            templates.DESCRIPTOR_BLOCK,
            constraints=constraints,
            keys=keys,
            fields=fields,
            storage=storage,
            array_layout=array_layout,
            record=record_definition,
            type=type_definition,
        )

    def _offset(self, record: RecordSchema, path: tuple[str, ...]) -> str:
        current = record
        pieces: list[str] = []
        for index, name in enumerate(path):
            pieces.append(f"offsetof({current.c_type}, {name})")
            if index + 1 < len(path):
                field = next(item for item in current.fields if item.name == name)
                current = self.records[field.type_id]
        return " + ".join(pieces)

    def _field_schema(self, record: RecordSchema, path: tuple[str, ...]) -> FieldSchema:
        current = record
        result: FieldSchema | None = None
        for index, name in enumerate(path):
            result = next(item for item in current.fields if item.name == name)
            if index + 1 < len(path):
                current = self.records[result.type_id]
        assert result is not None
        return result

    def _bounds(self, field: FieldSchema) -> _Bounds:
        item = self.types[field.type_id]
        flags: list[str] = []
        minimum = "{0}"
        maximum = "{0}"
        if item.kind is TypeKind.FLOAT:
            if field.minimum is not None:
                flags.append("JSON_REFLECT_HAS_MIN")
                minimum = f"{{.float_value = {field.minimum}}}"
            if field.maximum is not None:
                flags.append("JSON_REFLECT_HAS_MAX")
                maximum = f"{{.float_value = {field.maximum}}}"
            return _Bounds(tuple(flags), minimum, maximum)
        signed = bool(item.signed)
        bits = item.bits or 32
        low = -(1 << (bits - 1)) if signed else 0
        high = (1 << (bits - (1 if signed else 0))) - 1
        member = "signed_value" if signed else "unsigned_value"
        for name, raw, rounding in (
            ("MIN", field.minimum, ROUND_CEILING),
            ("MAX", field.maximum, ROUND_FLOOR),
        ):
            if raw is None:
                continue
            value = int(Decimal(raw).to_integral_value(rounding=rounding))
            if name == "MIN":
                if value > high:
                    flags.append("JSON_REFLECT_MIN_FAIL")
                elif value > low:
                    flags.append("JSON_REFLECT_HAS_MIN")
                    minimum = f"{{.{member} = {value}}}"
            elif value < low:
                flags.append("JSON_REFLECT_MAX_FAIL")
            elif value < high:
                flags.append("JSON_REFLECT_HAS_MAX")
                maximum = f"{{.{member} = {value}}}"
        return _Bounds(tuple(flags), minimum, maximum)

    def _constraints(
        self, record: RecordSchema, plan: TypePlan
    ) -> tuple[str, dict[int, str]]:
        definitions: list[str] = []
        names: dict[int, str] = {}
        for field in plan.fields:
            schema_field = self.fields[field.field_id]
            if not any(
                value is not None
                for value in (
                    schema_field.minimum,
                    schema_field.maximum,
                    schema_field.min_length,
                    schema_field.max_length,
                )
            ):
                continue
            name = f"{plan.record_descriptor}_field_{field.field_index}_constraints"
            names[field.field_index] = name
            bounds = self._bounds(schema_field)
            flags = list(bounds.flags)
            if schema_field.min_length is not None:
                flags.append("JSON_REFLECT_HAS_MIN_LENGTH")
            if schema_field.max_length is not None:
                flags.append("JSON_REFLECT_HAS_MAX_LENGTH")
            definitions.extend(
                (
                    f"static const json_reflect_constraints {name} = {{",
                    f"    .flags = {' | '.join(flags) if flags else '0'},",
                    f"    .minimum = {bounds.minimum},",
                    f"    .maximum = {bounds.maximum},",
                    f"    .min_length = {schema_field.min_length or 0},",
                    f"    .max_length = {schema_field.max_length or 0},",
                    "};",
                )
            )
        return "\n".join(definitions), names

    def _keys(self, plan: TypePlan) -> str:
        if not plan.key_entries:
            return ""
        name = f"{plan.record_descriptor}_keys"
        lines = [f"static const json_key_entry {name}[] = {{"]
        lines.extend(
            f"    {{{_c_slice(item.key)}, {item.field_index}}},"
            for item in plan.key_entries
        )
        lines.append("};")
        return "\n".join(lines)

    def _field_descriptors(
        self,
        record: RecordSchema,
        plan: TypePlan,
        constraint_names: dict[int, str],
    ) -> str:
        if not plan.fields:
            return ""
        name = f"{plan.record_descriptor}_fields"
        lines = [f"static const json_reflect_field {name}[] = {{"]
        for field in plan.fields:
            schema_field = self.fields[field.field_id]
            count_type = "NULL"
            count_offset = "SIZE_MAX"
            if field.length_path:
                count = self._field_schema(record, field.length_path)
                count_type = self._type_pointer(
                    count.type_id, self._field_expression(record, field.length_path)
                )
                count_offset = self._offset(record, field.length_path)
            constraints = constraint_names.get(field.field_index)
            lines.extend(
                (
                    "    {",
                    f"        .primary_key = {_c_slice(schema_field.key)},",
                    f"        .offset = {self._offset(record, field.path)},",
                    f"        .type = {self._type_pointer(schema_field.type_id, self._field_expression(record, field.path))},",
                    f"        .constraints = {'&' + constraints if constraints else 'NULL'},",
                    f"        .count_offset = {count_offset},",
                    f"        .count_type = {count_type},",
                    f"        .flags = {'JSON_REFLECT_REQUIRED' if schema_field.required else '0'},",
                    "    },",
                )
            )
        lines.append("};")
        return "\n".join(lines)

    def _storage(self, record: RecordSchema, plan: TypePlan) -> str:
        if not plan.owned_field_ids or record.shape is RecordShape.ARRAY:
            return ""
        name = f"{plan.record_descriptor}_storage"
        lines = [f"static const json_reflect_storage {name}[] = {{"]
        for field_id in plan.owned_field_ids:
            field = self.fields[field_id]
            count_type = "NULL"
            count_offset = "SIZE_MAX"
            if field.length_field_id:
                count = self.fields[field.length_field_id]
                count_type = self._type_pointer(
                    count.type_id,
                    self._field_expression(record, (count.name,)),
                )
                count_offset = f"offsetof({record.c_type}, {count.name})"
            lines.extend(
                (
                    "    {",
                    f"        .offset = offsetof({record.c_type}, {field.name}),",
                    f"        .type = &{self.descriptors[field.type_id]},",
                    f"        .count_offset = {count_offset},",
                    f"        .count_type = {count_type},",
                    "    },",
                )
            )
        lines.append("};")
        return "\n".join(lines)

    def _array_layout(self, record: RecordSchema, plan: TypePlan) -> str:
        if record.array is None:
            return ""
        layout = record.array
        elems = self.fields[layout.elems_field_id]
        length = self.fields[layout.length_field_id] if layout.length_field_id else None
        capacity = (
            self.fields[layout.capacity_field_id] if layout.capacity_field_id else None
        )
        name = f"{plan.record_descriptor}_array"
        element_type = self._type_pointer(
            layout.element_type_id,
            f"*(({record.c_type} *)0)->{elems.name}",
        )
        length_type = (
            self._type_pointer(
                length.type_id,
                self._field_expression(record, (length.name,)),
            )
            if length
            else "NULL"
        )
        capacity_type = (
            self._type_pointer(
                capacity.type_id,
                self._field_expression(record, (capacity.name,)),
            )
            if capacity
            else "NULL"
        )
        return "\n".join(
            (
                f"static const json_reflect_array_layout {name} = {{",
                f"    .elems_offset = offsetof({record.c_type}, {elems.name}),",
                f"    .element_type = {element_type},",
                f"    .length_offset = {'offsetof(' + record.c_type + ', ' + length.name + ')' if length else 'SIZE_MAX'},",
                f"    .length_type = {length_type},",
                f"    .capacity_offset = {'offsetof(' + record.c_type + ', ' + capacity.name + ')' if capacity else 'SIZE_MAX'},",
                f"    .capacity_type = {capacity_type},",
                "};",
            )
        )

    def _record_definition(self, record: RecordSchema, plan: TypePlan) -> str:
        keys = f"{plan.record_descriptor}_keys"
        fields = f"{plan.record_descriptor}_fields"
        storage = f"{plan.record_descriptor}_storage"
        return "\n".join(
            (
                f"static const json_reflect_record {plan.record_descriptor} = {{",
                f"    .shape = JSON_REFLECT_{record.shape.value.upper()},",
                f"    .size = sizeof({record.c_type}),",
                (
                    f"    .keys = {{{keys if plan.key_entries else 'NULL'}, "
                    f"{_array_size(keys) if plan.key_entries else '0'}}},"
                ),
                f"    .fields = {fields if plan.fields else 'NULL'},",
                f"    .field_count = {_array_size(fields) if plan.fields else '0'},",
                f"    .storage = {storage if plan.owned_field_ids and record.shape is RecordShape.OBJECT else 'NULL'},",
                f"    .storage_count = {_array_size(storage) if plan.owned_field_ids and record.shape is RecordShape.OBJECT else '0'},",
                f"    .array = {'&' + plan.record_descriptor + '_array' if record.array else 'NULL'},",
                "};",
            )
        )

    def _public_functions(self) -> str:
        functions: list[str] = []
        for function in self.schema.functions:
            descriptor = self.type_plans[function.record_id].type_descriptor
            template = (
                templates.PUBLIC_DECODE
                if function.role == "jsonDecode"
                else templates.PUBLIC_CLEANUP
            )
            functions.append(
                templates.render_c_template(
                    template,
                    function=function.name,
                    output_type=function.parameter_c_types[1].strip(),
                    descriptor=descriptor,
                )
            )
        return "\n\n".join(functions)


def generate_c(
    schema: Schema,
    plan: GeneratePlan,
    include: str,
    *,
    source_header: str,
    source_sha256: str,
) -> str:
    return CGenerator(schema, plan).generate(include, source_header, source_sha256)
