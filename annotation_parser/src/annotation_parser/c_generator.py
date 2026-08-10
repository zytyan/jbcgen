from __future__ import annotations

import json
from dataclasses import dataclass

from . import c_templates as templates
from .generate_plan import FieldPlan, GeneratePlan, TypePlan
from .schema import FieldSchema, RecordSchema, RecordShape, Schema, TypeKind


def _c_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=True)


@dataclass(frozen=True)
class _Constraint:
    minimum: str | None = None
    maximum: str | None = None
    min_length: int | None = None
    max_length: int | None = None


class CGenerator:
    def __init__(self, schema: Schema, plan: GeneratePlan):
        self.schema = schema
        self.types = schema.type_map()
        self.records = schema.record_map()
        self.fields = schema.field_map()
        self.type_plans = plan.type_map()

    def generate(self, include: str) -> str:
        prototypes: list[str] = []
        for record in self.schema.records:
            prototypes.extend(
                (
                    self._release_prototype(record) + ";",
                    self._decode_prototype(record) + ";",
                )
            )
            prototypes.extend(
                self._field_decode_prototype(field) + ";"
                for field in self.type_plans[record.id].fields
            )
        release_functions = "\n\n".join(
            self._generate_release(record) for record in self.schema.records
        )
        field_decode_functions = "\n\n".join(
            self._generate_field_decode(record, field)
            for record in self.schema.records
            for field in self.type_plans[record.id].fields
        )
        decode_functions = "\n\n".join(
            self._generate_decode(record) for record in self.schema.records
        )
        public_functions = self._generate_public_functions()
        function_source = (
            f"{release_functions}\n{field_decode_functions}\n"
            f"{decode_functions}\n{public_functions}"
        )
        result = templates.render_c_template(
            templates.C_FILE,
            include=_c_string(include),
            error_helpers=self._error_helpers(function_source),
            prototypes="\n".join(prototypes),
            release_functions=release_functions,
            field_decode_functions=field_decode_functions,
            decode_functions=decode_functions,
            public_functions=public_functions,
        )
        return result.rstrip() + "\n"

    def _release_name(self, record_id: str) -> str:
        return self.type_plans[record_id].release_helper

    def _decode_name(self, record_id: str) -> str:
        return self.type_plans[record_id].decode_helper

    def _release_prototype(self, record: RecordSchema) -> str:
        return f"static void {self._release_name(record.id)}(json_allocator *allocator, {record.c_type} *out)"

    def _decode_prototype(self, record: RecordSchema) -> str:
        return f"static bool {self._decode_name(record.id)}(json_parser *parser, {record.c_type} *out)"

    def _field_decode_prototype(self, field: FieldPlan) -> str:
        return f"static bool {field.decode_helper}(json_parser *parser, void *object)"

    def _error_helpers(self, function_source: str) -> str:
        helper_names = {
            "context": "jbc_set_context_error(",
            "length": "jbc_set_length_error(",
            "number": "jbc_set_number_error(",
            "memory": "jbc_set_no_memory(",
        }
        values = {
            kind: fragment.strip("\n") if helper_names[kind] in function_source else ""
            for kind, fragment in templates.ERROR_HELPER_FRAGMENTS.items()
        }
        return templates.render_c_template(templates.ERROR_HELPERS, **values)

    def _field_expression(self, path: tuple[str, ...], base: str = "out") -> str:
        return base + "->" + ".".join(path)

    def _field_schema(self, record: RecordSchema, path: tuple[str, ...]) -> FieldSchema:
        current = record
        result: FieldSchema | None = None
        for index, name in enumerate(path):
            result = next(field for field in current.fields if field.name == name)
            if index + 1 < len(path):
                current = self.records[result.type_id]
        assert result is not None
        return result

    def _generate_release(self, record: RecordSchema) -> str:
        plan = self.type_plans[record.id]
        if record.shape is RecordShape.ARRAY:
            return self._generate_array_release(record)
        body: list[str] = []
        for index, field_id in enumerate(plan.owned_field_ids):
            field = self.fields[field_id]
            expression = self._field_expression((field.name,))
            length_field = (
                self.fields[field.length_field_id] if field.length_field_id else None
            )
            length = (
                self._field_expression((length_field.name,)) if length_field else None
            )
            body.extend(
                self._emit_release_value(
                    field.type_id, expression, length, 1, f"r{index}"
                )
            )
        return templates.render_c_template(
            templates.OBJECT_RELEASE,
            prototype=self._release_prototype(record),
            body="\n".join(body),
        )

    def _generate_array_release(self, record: RecordSchema) -> str:
        layout = record.array
        assert layout is not None
        elems_field = self.fields[layout.elems_field_id]
        count_field_id = layout.length_field_id or layout.capacity_field_id
        elems = self._field_expression((elems_field.name,))
        element_release: list[str] = []
        if self.types[layout.element_type_id].owns_resources:
            assert count_field_id is not None
            count = self._field_expression((self.fields[count_field_id].name,))
            element_release.extend(
                [
                    f"    if ({elems} != NULL) {{",
                    f"        for (size_t r0 = 0; r0 < (size_t)({count}); ++r0) {{",
                ]
            )
            element_release.extend(
                self._emit_release_value(
                    layout.element_type_id, f"({elems})[r0]", None, 3, "r0e"
                )
            )
            element_release.append("        }")
            element_release.append("    }")
        return templates.render_c_template(
            templates.ARRAY_RECORD_RELEASE,
            prototype=self._release_prototype(record),
            element_release="\n".join(element_release),
            elems=elems,
        )

    def _emit_release_value(
        self,
        type_id: str,
        expression: str,
        length_expression: str | None,
        indent: int,
        variable: str,
        allocator: str = "allocator",
    ) -> list[str]:
        item = self.types[type_id]
        pad = "    " * indent
        lines: list[str] = []
        if item.kind is TypeKind.STRING and item.capacity is None:
            lines.extend(
                [
                    f"{pad}if ({expression} != NULL) {{",
                    f"{pad}    {allocator}->free({expression});",
                    f"{pad}    {expression} = NULL;",
                    f"{pad}}}",
                ]
            )
        elif item.kind is TypeKind.RECORD:
            lines.append(
                f"{pad}{self._release_name(item.id)}({allocator}, &({expression}));"
            )
        elif item.kind is TypeKind.POINTER and item.target is not None:
            lines.append(f"{pad}if ({expression} != NULL) {{")
            lines.extend(
                self._emit_release_value(
                    item.target,
                    f"*({expression})",
                    None,
                    indent + 1,
                    variable + "p",
                    allocator,
                )
            )
            lines.extend(
                [
                    f"{pad}    {allocator}->free({expression});",
                    f"{pad}    {expression} = NULL;",
                    f"{pad}}}",
                ]
            )
        elif (
            item.kind in {TypeKind.DYNAMIC_ARRAY, TypeKind.FIXED_ARRAY}
            and item.target is not None
        ):
            if item.kind is TypeKind.DYNAMIC_ARRAY:
                assert length_expression is not None
                count = length_expression
            elif length_expression is not None:
                count = length_expression
            else:
                count = str(item.capacity or 0)
            lines.append(
                f"{pad}for (size_t {variable} = 0; {variable} < (size_t)({count}); ++{variable}) {{"
            )
            lines.extend(
                self._emit_release_value(
                    item.target,
                    f"({expression})[{variable}]",
                    None,
                    indent + 1,
                    variable + "e",
                    allocator,
                )
            )
            lines.append(f"{pad}}}")
            if item.kind is TypeKind.DYNAMIC_ARRAY:
                lines.extend(
                    [
                        f"{pad}if ({expression} != NULL) {{",
                        f"{pad}    {allocator}->free({expression});",
                        f"{pad}    {expression} = NULL;",
                        f"{pad}}}",
                    ]
                )
            if length_expression is not None:
                lines.append(f"{pad}{length_expression} = 0;")
        return lines

    def _generate_decode(self, record: RecordSchema) -> str:
        plan = self.type_plans[record.id]
        if record.shape is RecordShape.ARRAY:
            return self._generate_array_decode(record)
        map_name = f"{plan.decode_helper}_key_map"
        primary_keys_name = f"{plan.decode_helper}_primary_keys"
        key_map = self._generate_key_map(plan, map_name, primary_keys_name)
        required_checks: list[str] = []
        for field in plan.fields:
            schema_field = self.fields[field.field_id]
            if schema_field.required:
                required_checks.extend(
                    [
                        f"    if (!seen[{field.seen_index}]) {{",
                        f"        jbc_set_context_error(parser, JSON_ERROR_OTHER_MISSING_REQUIRED_KEY, {_c_string(schema_field.key)}, object_end_location);",
                        "        goto fail;",
                        "    }",
                    ]
                )
        return templates.render_c_template(
            templates.OBJECT_DECODE,
            key_map=key_map,
            prototype=self._decode_prototype(record),
            seen_count=str(max(1, len(plan.fields))),
            map_name=map_name,
            primary_keys_name=primary_keys_name,
            required_checks="\n".join(required_checks),
            rollback_helper=plan.rollback_helper,
        )

    def _generate_key_map(
        self, plan: TypePlan, map_name: str, primary_keys_name: str
    ) -> str:
        entries_name = f"{plan.decode_helper}_key_entries"
        if plan.key_entries:
            entry_declaration = "\n".join(
                [
                    f"static const json_key_entry {entries_name}[] = {{",
                    *[
                        f"    {{{{{_c_string(entry.key)}, {len(entry.key.encode('utf-8'))}}}, "
                        f"{entry.field_index}, {entry.decode_helper}}},"
                        for entry in plan.key_entries
                    ],
                    "};",
                ]
            )
            entry_pointer = entries_name
            entry_count = f"sizeof({entries_name}) / sizeof({entries_name}[0])"
        else:
            entry_declaration = ""
            entry_pointer = "NULL"
            entry_count = "0"
        primary_values = [
            _c_string(self.fields[field.field_id].key) for field in plan.fields
        ] or ["NULL"]
        primary_key_declaration = "\n".join(
            [
                f"static const char *const {primary_keys_name}[] = {{",
                *[f"    {value}," for value in primary_values],
                "};",
            ]
        )
        return templates.render_c_template(
            templates.KEY_MAP,
            entry_declaration=entry_declaration,
            map_name=map_name,
            entry_pointer=entry_pointer,
            entry_count=entry_count,
            primary_key_declaration=primary_key_declaration,
        )

    def _generate_field_decode(self, record: RecordSchema, field: FieldPlan) -> str:
        schema_field = self.fields[field.field_id]
        expression = self._field_expression(field.path)
        length = (
            self._field_expression(field.length_path) if field.length_path else None
        )
        constraint = _Constraint(
            schema_field.minimum,
            schema_field.maximum,
            schema_field.min_length,
            schema_field.max_length,
        )
        body: list[str] = []
        if schema_field.required:
            body.extend(
                [
                    "    if (json_peek_token(parser)->kind == JSON_TOKEN_NULL) {",
                    f"        jbc_set_context_error(parser, JSON_ERROR_OTHER_NULL_REQUIRED_VALUE, {_c_string(schema_field.key)}, json_peek_token(parser)->location);",
                    "        goto fail;",
                    "    }",
                ]
            )
        body.extend(
            self._emit_decode_value(
                schema_field.type_id,
                expression,
                length,
                constraint,
                "fail",
                1,
                f"f{field.seen_index}",
                self._field_schema(record, field.length_path).type_id
                if field.length_path
                else None,
            )
        )
        return templates.render_c_template(
            templates.OBJECT_FIELD_DECODE,
            prototype=self._field_decode_prototype(field),
            object_type=record.c_type,
            body="\n".join(body),
        )

    def _counter_limit(self, type_id: str | None) -> int | None:
        if type_id is None:
            return None
        item = self.types[type_id]
        assert item.kind is TypeKind.INTEGER and not item.signed
        bits = item.bits or 64
        # The supported target is LP64, so a 64-bit unsigned counter can hold size_t.
        return (1 << bits) - 1 if bits < 64 else None

    def _emit_counter_check(
        self,
        value: str,
        type_id: str | None,
        location: str,
        fail_label: str,
        indent: int,
    ) -> list[str]:
        limit = self._counter_limit(type_id)
        if limit is None:
            return []
        pad = "    " * indent
        return [
            f"{pad}if ({value} > (size_t){limit}) {{",
            f"{pad}    jbc_set_length_error(parser, JSON_ERROR_RANGE_ARRAY_LENGTH, JSON_RANGE_ARRAY_LENGTH, {limit}, {location});",
            f"{pad}    goto {fail_label};",
            f"{pad}}}",
        ]

    def _generate_array_decode(self, record: RecordSchema) -> str:
        layout = record.array
        assert layout is not None
        target = self.types[layout.element_type_id]
        elems_field = self.fields[layout.elems_field_id]
        length_field = (
            self.fields[layout.length_field_id] if layout.length_field_id else None
        )
        capacity_field = (
            self.fields[layout.capacity_field_id] if layout.capacity_field_id else None
        )
        elems = self._field_expression((elems_field.name,))
        length = self._field_expression((length_field.name,)) if length_field else None
        capacity = (
            self._field_expression((capacity_field.name,)) if capacity_field else None
        )
        length_type_id = length_field.type_id if length_field else None
        capacity_type_id = capacity_field.type_id if capacity_field else None
        location_declaration = (
            "    json_source_location array_location = "
            "json_peek_token(parser)->location;"
            if self._counter_limit(capacity_type_id) is not None
            else ""
        )
        # Reject before decoding the first element that cannot be represented by len.
        limit = self._counter_limit(length_type_id)
        length_guard: list[str] = []
        if limit is not None:
            length_guard.extend(
                [
                    f"            if (array_count >= (size_t){limit}) {{",
                    f"                jbc_set_length_error(parser, JSON_ERROR_RANGE_ARRAY_LENGTH, JSON_RANGE_ARRAY_LENGTH, {limit}, json_peek_token(parser)->location);",
                    "                goto array_fail;",
                    "            }",
                ]
            )
        decode_element = self._emit_decode_value(
            layout.element_type_id,
            "*array_element",
            None,
            _Constraint(),
            "array_fail",
            3,
            "array_element",
        )
        capacity_result: list[str] = []
        if capacity is not None:
            capacity_result.append(
                f"    size_t array_capacity = array_vec.byte_cap / sizeof({target.c_type});"
            )
            capacity_result.extend(
                self._emit_counter_check(
                    "array_capacity",
                    capacity_type_id,
                    "array_location",
                    "array_fail",
                    1,
                )
            )
        length_result = ""
        if length is not None:
            assert length_field is not None
            length_result = f"    {length} = ({length_field.c_type})array_count;"
        capacity_assignment = ""
        if capacity is not None:
            assert capacity_field is not None
            capacity_assignment = (
                f"    {capacity} = ({capacity_field.c_type})array_capacity;"
            )
        release_element = self._emit_release_value(
            layout.element_type_id,
            f"(({target.c_type} *)array_vec.data)[array_cleanup]",
            None,
            2,
            "array_cleanup_element",
            "parser->allocator",
        )
        return templates.render_c_template(
            templates.ARRAY_RECORD_DECODE,
            prototype=self._decode_prototype(record),
            location_declaration=location_declaration,
            elems=elems,
            length_init=f"    {length} = 0;" if length is not None else "",
            capacity_init=f"    {capacity} = 0;" if capacity is not None else "",
            length_guard="\n".join(length_guard),
            element_type=target.c_type,
            decode_element="\n".join(decode_element),
            capacity_result="\n".join(capacity_result),
            length_result=length_result,
            capacity_assignment=capacity_assignment,
            release_element="\n".join(release_element),
            rollback_helper=self._release_name(record.id),
        )

    def _emit_decode_value(
        self,
        type_id: str,
        expression: str,
        length_expression: str | None,
        constraint: _Constraint,
        fail_label: str,
        indent: int,
        variable: str,
        length_type_id: str | None = None,
    ) -> list[str]:
        item = self.types[type_id]
        pad = "    " * indent
        lines: list[str] = []
        if item.kind is TypeKind.BOOL:
            lines.append(
                f"{pad}if (!json_decode_bool(parser, &({expression}))) goto {fail_label};"
            )
        elif item.kind in {TypeKind.INTEGER, TypeKind.ENUM}:
            bits = item.bits or 32
            signed = bool(item.signed)
            function = f"json_decode_{'i' if signed else 'u'}{bits}"
            needs_location = (
                constraint.minimum is not None or constraint.maximum is not None
            )
            if item.kind is TypeKind.ENUM:
                temp_type = f"{'int' if signed else 'uint'}{bits}_t"
                lines.append(f"{pad}{temp_type} {variable}_number = 0;")
                if needs_location:
                    lines.append(
                        f"{pad}json_source_location {variable}_location = json_peek_token(parser)->location;"
                    )
                    lines.append(
                        f"{pad}json_error_span {variable}_span = {{json_peek_token(parser)->str.ptr, json_peek_token(parser)->str.ptr + json_peek_token(parser)->str.len}};"
                    )
                lines.append(
                    f"{pad}if (!{function}(parser, &{variable}_number)) goto {fail_label};"
                )
                lines.append(f"{pad}{expression} = ({item.c_type}){variable}_number;")
            else:
                if needs_location:
                    lines.append(
                        f"{pad}json_source_location {variable}_location = json_peek_token(parser)->location;"
                    )
                    lines.append(
                        f"{pad}json_error_span {variable}_span = {{json_peek_token(parser)->str.ptr, json_peek_token(parser)->str.ptr + json_peek_token(parser)->str.len}};"
                    )
                lines.append(
                    f"{pad}if (!{function}(parser, &({expression}))) goto {fail_label};"
                )
            lines.extend(
                self._emit_number_constraints(
                    expression, constraint, variable, fail_label, indent
                )
            )
        elif item.kind is TypeKind.FLOAT:
            needs_location = (
                item.bits == 32
                or constraint.minimum is not None
                or constraint.maximum is not None
            )
            if needs_location:
                lines.append(
                    f"{pad}json_source_location {variable}_location = json_peek_token(parser)->location;"
                )
                lines.append(
                    f"{pad}json_error_span {variable}_span = {{json_peek_token(parser)->str.ptr, json_peek_token(parser)->str.ptr + json_peek_token(parser)->str.len}};"
                )
            if item.bits == 32:
                lines.append(f"{pad}double {variable}_number = 0.0;")
                lines.append(
                    f"{pad}if (!json_decode_f64(parser, &{variable}_number)) goto {fail_label};"
                )
                lines.append(
                    f"{pad}if ({variable}_number < -FLT_MAX || {variable}_number > FLT_MAX) {{"
                )
                lines.append(
                    f"{pad}    jbc_set_number_error(parser, {variable}_location, {variable}_span);"
                )
                lines.append(f"{pad}    goto {fail_label};")
                lines.append(f"{pad}}}")
                lines.append(f"{pad}{expression} = (float){variable}_number;")
            else:
                lines.append(
                    f"{pad}if (!json_decode_f64(parser, &({expression}))) goto {fail_label};"
                )
            lines.extend(
                self._emit_number_constraints(
                    expression, constraint, variable, fail_label, indent
                )
            )
        elif item.kind is TypeKind.STRING:
            lines.extend(
                self._emit_string(
                    item, expression, constraint, fail_label, indent, variable
                )
            )
        elif item.kind is TypeKind.RECORD:
            lines.append(
                f"{pad}if (!{self._decode_name(item.id)}(parser, &({expression}))) goto {fail_label};"
            )
        elif item.kind is TypeKind.POINTER and item.target is not None:
            lines.extend(
                self._emit_pointer(item, expression, fail_label, indent, variable)
            )
        elif item.kind is TypeKind.FIXED_ARRAY and item.target is not None:
            lines.extend(
                self._emit_fixed_array(
                    item,
                    expression,
                    length_expression,
                    length_type_id,
                    constraint,
                    fail_label,
                    indent,
                    variable,
                )
            )
        elif item.kind is TypeKind.DYNAMIC_ARRAY and item.target is not None:
            assert length_expression is not None
            lines.extend(
                self._emit_dynamic_array(
                    item,
                    expression,
                    length_expression,
                    length_type_id,
                    constraint,
                    fail_label,
                    indent,
                    variable,
                )
            )
        else:
            raise AssertionError(f"unsupported decode type {item}")
        return lines

    def _emit_number_constraints(
        self,
        expression: str,
        constraint: _Constraint,
        variable: str,
        fail_label: str,
        indent: int,
    ) -> list[str]:
        conditions = []
        if constraint.minimum is not None:
            conditions.append(f"({expression}) < ({constraint.minimum})")
        if constraint.maximum is not None:
            conditions.append(f"({expression}) > ({constraint.maximum})")
        if not conditions:
            return []
        pad = "    " * indent
        return [
            f"{pad}if ({' || '.join(conditions)}) {{",
            f"{pad}    jbc_set_number_error(parser, {variable}_location, {variable}_span);",
            f"{pad}    goto {fail_label};",
            f"{pad}}}",
        ]

    def _emit_string(
        self, item, expression, constraint, fail_label, indent, variable
    ) -> list[str]:
        pad = "    " * indent
        lines: list[str] = []
        nullable = item.capacity is None
        if nullable:
            lines.extend(
                [
                    f"{pad}if (json_peek_token(parser)->kind == JSON_TOKEN_NULL) {{",
                    f"{pad}    if (!json_decode_null(parser)) goto {fail_label};",
                    f"{pad}}} else {{",
                ]
            )
            body_indent = indent + 1
        else:
            body_indent = indent
        body = "    " * body_indent
        lines.extend(
            [
                f"{body}json_source_location {variable}_location = json_peek_token(parser)->location;",
                f"{body}json_cow_str {variable}_string = {{0}};",
                f"{body}if (!json_decode_string(parser, &{variable}_string)) goto {fail_label};",
                f"{body}json_slice {variable}_slice = json_cow_str_as_slice(&{variable}_string);",
                f"{body}size_t {variable}_length = {variable}_slice.len;",
                f"{body}if (memchr({variable}_slice.ptr, '\\0', {variable}_length) != NULL) {{",
                f"{body}    json_free_cow_str(parser->allocator, &{variable}_string);",
                f"{body}    json_set_error_at(parser, JSON_ERROR_OTHER_EMBEDDED_NUL, NULL, {variable}_location);",
                f"{body}    goto {fail_label};",
                f"{body}}}",
            ]
        )
        limits: list[tuple[str, int]] = []
        if constraint.min_length is not None:
            limits.append(
                (f"{variable}_length < {constraint.min_length}", constraint.min_length)
            )
        if constraint.max_length is not None:
            limits.append(
                (f"{variable}_length > {constraint.max_length}", constraint.max_length)
            )
        if item.capacity is not None:
            limits.append(
                (f"{variable}_length >= {item.capacity}", max(0, item.capacity - 1))
            )
        for condition, limit in limits:
            lines.extend(
                [
                    f"{body}if ({condition}) {{",
                    f"{body}    json_free_cow_str(parser->allocator, &{variable}_string);",
                    f"{body}    jbc_set_length_error(parser, JSON_ERROR_RANGE_STRING_LENGTH, JSON_RANGE_STRING_LENGTH, {limit}, {variable}_location);",
                    f"{body}    goto {fail_label};",
                    f"{body}}}",
                ]
            )
        if item.capacity is None:
            lines.extend(
                [
                    f"{body}json_error_code {variable}_code = json_cow_str_into_owned_c_str(parser->allocator, &{variable}_string, &({expression}));",
                    f"{body}if ({variable}_code != JSON_ERROR_NONE) {{",
                    f"{body}    json_free_cow_str(parser->allocator, &{variable}_string);",
                    f"{body}    json_set_error_at(parser, {variable}_code, NULL, {variable}_location);",
                    f"{body}    goto {fail_label};",
                    f"{body}}}",
                ]
            )
        else:
            lines.extend(
                [
                    f"{body}size_t {variable}_written = 0;",
                    f"{body}(void)json_slice_write_to_buf(&{variable}_slice, {expression}, {item.capacity}, &{variable}_written);",
                    f"{body}json_free_cow_str(parser->allocator, &{variable}_string);",
                ]
            )
        if nullable:
            lines.append(f"{pad}}}")
        return lines

    def _emit_pointer(
        self, item, expression, fail_label, indent, variable
    ) -> list[str]:
        pad = "    " * indent
        pointer_fail = f"{variable}_pointer_fail"
        pointer_done = f"{variable}_pointer_done"
        target = self.types[item.target]
        lines = [
            f"{pad}if (json_peek_token(parser)->kind == JSON_TOKEN_NULL) {{",
            f"{pad}    if (!json_decode_null(parser)) goto {fail_label};",
            f"{pad}}} else {{",
        ]
        if target.kind is TypeKind.RECORD:
            target_record = self.records[target.id]
            token = (
                "JSON_TOKEN_LBRACKET"
                if target_record.shape is RecordShape.ARRAY
                else "JSON_TOKEN_LBRACE"
            )
            expected = (
                "JSON_EXPECTED_ARRAY"
                if target_record.shape is RecordShape.ARRAY
                else "JSON_EXPECTED_OBJECT"
            )
            lines.extend(
                [
                    f"{pad}    if (json_peek_token(parser)->kind != {token}) {{",
                    f"{pad}        json_error_detail {variable}_type_error = {{0}};",
                    f"{pad}        {variable}_type_error.type.expected = {expected};",
                    f"{pad}        {variable}_type_error.type.actual = json_peek_token(parser)->kind;",
                    f"{pad}        json_set_error(parser, JSON_ERROR_TYPE_MISMATCH, &{variable}_type_error);",
                    f"{pad}        goto {fail_label};",
                    f"{pad}    }}",
                ]
            )
        lines.extend(
            [
                f"{pad}    {expression} = ({target.c_type} *)parser->allocator->malloc(sizeof(*({expression})));",
                f"{pad}    if ({expression} == NULL) {{",
                f"{pad}        jbc_set_no_memory(parser);",
                f"{pad}        goto {fail_label};",
                f"{pad}    }}",
                f"{pad}    memset({expression}, 0, sizeof(*({expression})));",
            ]
        )
        lines.extend(
            self._emit_decode_value(
                item.target,
                f"*({expression})",
                None,
                _Constraint(),
                pointer_fail,
                indent + 1,
                variable + "p",
            )
        )
        lines.extend(
            [
                f"{pad}    goto {pointer_done};",
                f"{pointer_fail}:",
            ]
        )
        lines.extend(
            self._emit_release_value(
                item.target,
                f"*({expression})",
                None,
                indent + 1,
                variable + "pr",
                "parser->allocator",
            )
        )
        lines.extend(
            [
                f"{pad}    parser->allocator->free({expression});",
                f"{pad}    {expression} = NULL;",
                f"{pad}    goto {fail_label};",
                f"{pointer_done}: ;",
                f"{pad}}}",
            ]
        )
        return lines

    def _emit_array_length_checks(
        self,
        count: str,
        constraint: _Constraint,
        fail_label: str,
        indent: int,
        variable: str,
    ) -> list[str]:
        pad = "    " * indent
        lines: list[str] = []
        for operator, limit in (
            ("<", constraint.min_length),
            (">", constraint.max_length),
        ):
            if limit is None:
                continue
            lines.extend(
                [
                    f"{pad}if ({count} {operator} {limit}) {{",
                    f"{pad}    jbc_set_length_error(parser, JSON_ERROR_RANGE_ARRAY_LENGTH, JSON_RANGE_ARRAY_LENGTH, {limit}, {variable}_location);",
                    f"{pad}    goto {fail_label};",
                    f"{pad}}}",
                ]
            )
        return lines

    def _emit_fixed_array(
        self,
        item,
        expression,
        length_expression,
        length_type_id,
        constraint,
        fail_label,
        indent,
        variable,
    ):
        pad = "    " * indent
        capacity = item.capacity or 0
        lines = [f"{pad}size_t {variable}_count = 0;"]
        if constraint.min_length is not None or constraint.max_length is not None:
            lines.insert(
                0,
                f"{pad}json_source_location {variable}_location = json_peek_token(parser)->location;",
            )
        if length_expression:
            lines.append(f"{pad}{length_expression} = 0;")
        lines.extend(
            [
                f"{pad}if (!json_array_begin(parser)) goto {fail_label};",
                f"{pad}if (!json_array_try_end(parser)) {{",
                f"{pad}while (true) {{",
                f"{pad}    if ({variable}_count >= {capacity}) {{",
                f"{pad}        jbc_set_length_error(parser, JSON_ERROR_RANGE_ARRAY_LENGTH, JSON_RANGE_ARRAY_LENGTH, {capacity}, json_peek_token(parser)->location);",
                f"{pad}        goto {fail_label};",
                f"{pad}    }}",
            ]
        )
        if constraint.max_length is not None and constraint.max_length < capacity:
            lines.extend(
                [
                    f"{pad}    if ({variable}_count >= {constraint.max_length}) {{",
                    f"{pad}        jbc_set_length_error(parser, JSON_ERROR_RANGE_ARRAY_LENGTH, JSON_RANGE_ARRAY_LENGTH, {constraint.max_length}, json_peek_token(parser)->location);",
                    f"{pad}        goto {fail_label};",
                    f"{pad}    }}",
                ]
            )
        length_limit = self._counter_limit(length_type_id)
        if length_limit is not None:
            lines.extend(
                [
                    f"{pad}    if ({variable}_count >= (size_t){length_limit}) {{",
                    f"{pad}        jbc_set_length_error(parser, JSON_ERROR_RANGE_ARRAY_LENGTH, JSON_RANGE_ARRAY_LENGTH, {length_limit}, json_peek_token(parser)->location);",
                    f"{pad}        goto {fail_label};",
                    f"{pad}    }}",
                ]
            )
        if length_expression:
            # Include the zero-initialized current slot in rollback if element decoding fails.
            lines.extend(
                [
                    f"{pad}    ++{variable}_count;",
                    f"{pad}    {length_expression} = {variable}_count;",
                ]
            )
        lines.extend(
            self._emit_decode_value(
                item.target,
                (
                    f"({expression})[{variable}_count - 1]"
                    if length_expression
                    else f"({expression})[{variable}_count]"
                ),
                None,
                _Constraint(),
                fail_label,
                indent + 1,
                variable + "e",
            )
        )
        if not length_expression:
            lines.append(f"{pad}    ++{variable}_count;")
        lines.extend(
            [
                f"{pad}    if (json_peek_token(parser)->kind == JSON_TOKEN_RBRACKET) {{",
                f"{pad}        if (!json_array_try_end(parser)) goto {fail_label};",
                f"{pad}        break;",
                f"{pad}    }}",
                f"{pad}    if (!json_consume_comma(parser)) goto {fail_label};",
                f"{pad}}}",
                f"{pad}}}",
            ]
        )
        lines.extend(
            self._emit_array_length_checks(
                f"{variable}_count", constraint, fail_label, indent, variable
            )
        )
        return lines

    def _emit_dynamic_array(
        self,
        item,
        expression,
        length_expression,
        length_type_id,
        constraint,
        fail_label,
        indent,
        variable,
    ):
        pad = "    " * indent
        target = self.types[item.target]
        array_fail = f"{variable}_array_fail"
        array_done = f"{variable}_array_done"
        lines = [
            f"{pad}{expression} = NULL;",
            f"{pad}{length_expression} = 0;",
            f"{pad}if (json_peek_token(parser)->kind == JSON_TOKEN_NULL) {{",
            f"{pad}    if (!json_decode_null(parser)) goto {fail_label};",
            f"{pad}}} else {{",
            f"{pad}    json_any_vec {variable}_vec = {{0}};",
            f"{pad}    size_t {variable}_count = 0;",
            f"{pad}    if (!json_array_begin(parser)) goto {array_fail};",
            f"{pad}    if (!json_array_try_end(parser)) {{",
            f"{pad}    while (true) {{",
        ]
        if constraint.min_length is not None or constraint.max_length is not None:
            lines.insert(
                6,
                f"{pad}    json_source_location {variable}_location = json_peek_token(parser)->location;",
            )
        if constraint.max_length is not None:
            lines.extend(
                [
                    f"{pad}        if ({variable}_count >= {constraint.max_length}) {{",
                    f"{pad}            jbc_set_length_error(parser, JSON_ERROR_RANGE_ARRAY_LENGTH, JSON_RANGE_ARRAY_LENGTH, {constraint.max_length}, json_peek_token(parser)->location);",
                    f"{pad}            goto {array_fail};",
                    f"{pad}        }}",
                ]
            )
        length_limit = self._counter_limit(length_type_id)
        if length_limit is not None:
            lines.extend(
                [
                    f"{pad}        if ({variable}_count >= (size_t){length_limit}) {{",
                    f"{pad}            jbc_set_length_error(parser, JSON_ERROR_RANGE_ARRAY_LENGTH, JSON_RANGE_ARRAY_LENGTH, {length_limit}, json_peek_token(parser)->location);",
                    f"{pad}            goto {array_fail};",
                    f"{pad}        }}",
                ]
            )
        lines.extend(
            [
                f"{pad}        if (!json_any_vec_reserve(parser->allocator, &{variable}_vec, sizeof({target.c_type}))) {{",
                f"{pad}            jbc_set_no_memory(parser);",
                f"{pad}            goto {array_fail};",
                f"{pad}        }}",
                f"{pad}        {target.c_type} *{variable}_element = ({target.c_type} *)({variable}_vec.data + {variable}_vec.byte_len);",
                f"{pad}        {variable}_vec.byte_len += sizeof({target.c_type});",
                f"{pad}        ++{variable}_count;",
            ]
        )
        lines.extend(
            self._emit_decode_value(
                item.target,
                f"*{variable}_element",
                None,
                _Constraint(),
                array_fail,
                indent + 2,
                variable + "e",
            )
        )
        lines.extend(
            [
                f"{pad}        if (json_peek_token(parser)->kind == JSON_TOKEN_RBRACKET) {{",
                f"{pad}            if (!json_array_try_end(parser)) goto {array_fail};",
                f"{pad}            break;",
                f"{pad}        }}",
                f"{pad}        if (!json_consume_comma(parser)) goto {array_fail};",
                f"{pad}    }}",
                f"{pad}    }}",
            ]
        )
        lines.extend(
            self._emit_array_length_checks(
                f"{variable}_count", constraint, array_fail, indent + 1, variable
            )
        )
        lines.extend(
            [
                f"{pad}    {expression} = ({target.c_type} *){variable}_vec.data;",
                f"{pad}    {length_expression} = {variable}_count;",
                f"{pad}    {variable}_vec.data = NULL;",
                f"{pad}    goto {array_done};",
                f"{array_fail}:",
                f"{pad}    for (size_t {variable}_cleanup = 0; {variable}_cleanup < {variable}_count; ++{variable}_cleanup) {{",
            ]
        )
        lines.extend(
            self._emit_release_value(
                item.target,
                f"(({target.c_type} *){variable}_vec.data)[{variable}_cleanup]",
                None,
                indent + 2,
                variable + "c",
                "parser->allocator",
            )
        )
        lines.extend(
            [
                f"{pad}    }}",
                f"{pad}    if ({variable}_vec.data != NULL) parser->allocator->free({variable}_vec.data);",
                f"{pad}    goto {fail_label};",
                f"{array_done}: ;",
                f"{pad}}}",
            ]
        )
        return lines

    def _generate_public_functions(self) -> str:
        functions: list[str] = []
        for function in self.schema.functions:
            if function.role != "jsonDecode":
                continue
            output_type = function.parameter_c_types[1].strip()
            functions.append(
                templates.render_c_template(
                    templates.PUBLIC_DECODE,
                    function=function.name,
                    output_type=output_type,
                    decode_helper=self._decode_name(function.record_id),
                )
            )
        for function in self.schema.functions:
            if function.role != "jsonCleanup":
                continue
            output_type = function.parameter_c_types[1].strip()
            functions.append(
                templates.render_c_template(
                    templates.PUBLIC_CLEANUP,
                    function=function.name,
                    output_type=output_type,
                    release_helper=self._release_name(function.record_id),
                )
            )
        return "\n\n".join(functions)


def generate_c(schema: Schema, plan: GeneratePlan, include: str) -> str:
    return CGenerator(schema, plan).generate(include)
