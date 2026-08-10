from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from ..annotations import Annotation
from ..clang_frontend import AstRecord, AstTypeKind
from ..diagnostics import AnnotationError
from ..schema_core import CoreFieldSchema, CoreTypeKind, CoreTypeSchema
from .base import (
    AnnotationCommandSpec,
    PluginBuildContext,
    PluginKey,
    PluginValidationContext,
    SchemaPluginBase,
    argument_value,
    find_annotation,
    flag_argument,
    frozen_map,
    has_flag,
    value_argument,
)


@dataclass(frozen=True)
class FunctionEntrypoint:
    function_id: str
    role: str
    record_id: str | None


@dataclass(frozen=True)
class EntrypointsState:
    public_record_ids: tuple[str, ...]
    functions: tuple[FunctionEntrypoint, ...]

    def root_record_names(self) -> tuple[str, ...]:
        names = {item.removeprefix("record:") for item in self.public_record_ids}
        names.update(
            item.record_id.removeprefix("record:")
            for item in self.functions
            if item.record_id is not None
        )
        return tuple(sorted(names))

    def function_names(self) -> tuple[str, ...]:
        return tuple(
            sorted(item.function_id.removeprefix("function:") for item in self.functions)
        )


ENTRYPOINTS_KEY = PluginKey("jbcgen.json.entrypoints.v1", EntrypointsState)


class EntrypointsPlugin(SchemaPluginBase[EntrypointsState]):
    key = ENTRYPOINTS_KEY
    annotation_commands = (
        AnnotationCommandSpec("jsonStruct"),
        AnnotationCommandSpec("jsonDecode"),
        AnnotationCommandSpec("jsonCleanup"),
    )

    def build(self, context: PluginBuildContext) -> EntrypointsState:
        unit = context.unit
        public_records: list[str] = []
        for record in unit.records:
            if find_annotation(record.annotations, "jsonStruct", record.location) is not None:
                public_records.append(f"record:{record.name}")

        functions: list[FunctionEntrypoint] = []
        records = {record.name for record in unit.records}
        for function in unit.functions:
            for role in ("jsonDecode", "jsonCleanup"):
                if find_annotation(function.annotations, role, function.location) is None:
                    continue
                record_id = None
                if len(function.parameters) >= 2:
                    item = function.parameters[1].type
                    if (
                        item.kind is AstTypeKind.POINTER
                        and item.target is not None
                        and item.target.kind is AstTypeKind.RECORD
                        and item.target.name in records
                    ):
                        record_id = f"record:{item.target.name}"
                functions.append(
                    FunctionEntrypoint(f"function:{function.name}", role, record_id)
                )
        return EntrypointsState(
            tuple(sorted(set(public_records))),
            tuple(sorted(functions, key=lambda item: (item.role, item.function_id))),
        )

    def validate(
        self, context: PluginValidationContext, state: EntrypointsState
    ) -> None:
        unit = context.unit
        functions = {f"function:{item.name}": item for item in unit.functions}
        public = set(state.public_record_ids)
        cleanups = {
            item.record_id for item in state.functions if item.role == "jsonCleanup"
        }
        for entry in state.functions:
            function = functions[entry.function_id]
            if entry.role == "jsonDecode":
                if function.return_type.kind is not AstTypeKind.BOOL or len(function.parameters) != 2:
                    raise AnnotationError(
                        "@jsonDecode requires bool function(json_parser *, T *)",
                        function.location,
                    )
                expected_first = "json_parser"
            else:
                if function.return_type.kind is not AstTypeKind.VOID or len(function.parameters) != 2:
                    raise AnnotationError(
                        "@jsonCleanup requires void function(json_allocator *, T *)",
                        function.location,
                    )
                expected_first = "json_allocator"
            first = function.parameters[0].type
            if (
                first.kind is not AstTypeKind.POINTER
                or first.target is None
                or first.target.name != expected_first
            ):
                raise AnnotationError(
                    f"the first @{entry.role} parameter must be {expected_first} *",
                    function.location,
                )
            if entry.record_id is None:
                raise AnnotationError(
                    f"the second @{entry.role} parameter must point to a known structure",
                    function.location,
                )
            if entry.role == "jsonDecode" and entry.record_id not in public:
                raise AnnotationError("the @jsonDecode target must have @jsonStruct", function.location)
            if entry.role == "jsonDecode" and entry.record_id not in cleanups:
                raise AnnotationError(
                    "each @jsonDecode target requires an @jsonCleanup function",
                    function.location,
                )

    def format_state(self, state: EntrypointsState) -> str:
        lines = [f"public {item}" for item in state.public_record_ids]
        lines.extend(
            f"{item.role} {item.function_id} -> {item.record_id or '?'}"
            for item in state.functions
        )
        return "\n".join(lines)


@dataclass(frozen=True)
class FieldBinding:
    key: str
    altkeys: tuple[str, ...]
    required: bool
    flatten: bool
    explicit_key: bool


@dataclass(frozen=True)
class BindingState:
    fields: Mapping[str, FieldBinding]


BINDING_KEY = PluginKey("jbcgen.json.binding.v1", BindingState)


class BindingPlugin(SchemaPluginBase[BindingState]):
    key = BINDING_KEY
    annotation_commands = (
        AnnotationCommandSpec(
            "json",
            (
                value_argument("key"),
                value_argument("altkey", repeatable=True),
                flag_argument("required"),
                flag_argument("flatten"),
            ),
        ),
    )

    def build(self, context: PluginBuildContext) -> BindingState:
        unit = context.unit
        core = context.core
        assert core is not None
        ast_records = {item.name: item for item in unit.records}
        bindings: dict[str, FieldBinding] = {}
        for record in core.records:
            ast_fields = {item.name: item for item in ast_records[record.name].fields}
            for field in record.fields:
                ast_field = ast_fields[field.name]
                annotation = find_annotation(ast_field.annotations, "json", ast_field.location)
                altkeys = tuple(
                    value for value in (annotation.values("altkey") if annotation else ())
                    if value is not None
                )
                bindings[field.id] = FieldBinding(
                    argument_value(annotation, "key") or field.name,
                    altkeys,
                    has_flag(annotation, "required"),
                    has_flag(annotation, "flatten"),
                    argument_value(annotation, "key") is not None,
                )
        return BindingState(frozen_map(bindings.items()))

    def validate(
        self, context: PluginValidationContext, state: BindingState
    ) -> None:
        # Imported lazily because Value/Constraints plugins derive from the
        # structural states defined in this module.
        from .semantics import CONSTRAINTS_KEY

        core = context.core
        plugins = context.states
        bindings = state.fields
        types = core.type_map()
        records = core.record_map()
        for field in core.field_map().values():
            binding = bindings[field.id]
            if binding.required and binding.flatten:
                raise AnnotationError(
                    "required cannot be combined with flatten", field.location
                )
            if binding.flatten and types[field.type_id].kind is not CoreTypeKind.RECORD:
                raise AnnotationError(
                    "flatten requires a by-value structure field", field.location
                )

        array_layout = plugins.get(ARRAY_LAYOUT_KEY)
        array_records = (
            set(array_layout.records) if array_layout else set()
        )
        metadata = array_layout.metadata_field_ids() if array_layout else frozenset()
        ignored = (
            {
                field_id
                for item in array_layout.records.values()
                for field_id in item.ignored_field_ids
            }
            if array_layout
            else set()
        )
        constraint_state = plugins.get(CONSTRAINTS_KEY)
        constraints = constraint_state.fields if constraint_state else {}
        array_fields = array_layout.fields if array_layout else {}
        for field_id, binding in bindings.items():
            if not binding.flatten:
                continue
            field = core.field_map()[field_id]
            if (
                binding.explicit_key
                or field_id in array_fields
                or field_id in constraints
            ):
                raise AnnotationError(
                    "flatten cannot be combined with key, len, or constraints",
                    field.location,
                )

        def add_record(record_id: str, keys: dict[str, str], prefix: str) -> None:
            for field in records[record_id].fields:
                if field.id in metadata or field.id in ignored:
                    continue
                binding = bindings[field.id]
                if binding.flatten:
                    add_record(field.type_id, keys, prefix + field.name + ".")
                    continue
                for key in (binding.key, *binding.altkeys):
                    previous = keys.get(key)
                    if previous is not None:
                        raise AnnotationError(
                            f"JSON key {key!r} is shared by {previous} and {prefix + field.name}",
                            field.location,
                        )
                    keys[key] = prefix + field.name

        for record in core.records:
            if record.id in array_records:
                continue
            add_record(record.id, {}, "")

    def format_state(self, state: BindingState) -> str:
        lines = []
        for field_id, item in state.fields.items():
            flags = []
            if item.required:
                flags.append("required")
            if item.flatten:
                flags.append("flatten")
            suffix = f" [{' '.join(flags)}]" if flags else ""
            aliases = f" altkeys={item.altkeys!r}" if item.altkeys else ""
            lines.append(f"{field_id} key={item.key!r}{aliases}{suffix}")
        return "\n".join(lines)


@dataclass(frozen=True)
class FieldArrayLayout:
    length_field_id: str
    dynamic: bool


@dataclass(frozen=True)
class RecordArrayLayout:
    elems_field_id: str
    element_type_id: str
    length_field_id: str | None
    capacity_field_id: str | None
    ignored_field_ids: tuple[str, ...]


@dataclass(frozen=True)
class ArrayLayoutState:
    fields: Mapping[str, FieldArrayLayout]
    records: Mapping[str, RecordArrayLayout]

    def metadata_field_ids(self) -> frozenset[str]:
        return frozenset(item.length_field_id for item in self.fields.values())


ARRAY_LAYOUT_KEY = PluginKey("jbcgen.json.array-layout.v1", ArrayLayoutState)


class ArrayLayoutPlugin(SchemaPluginBase[ArrayLayoutState]):
    key = ARRAY_LAYOUT_KEY
    annotation_commands = (
        AnnotationCommandSpec(
            "json",
            (
                value_argument("type"),
                value_argument("len"),
            ),
        ),
        AnnotationCommandSpec(
            "jsonStruct",
            (
                flag_argument("asarray"),
                value_argument("elems"),
                value_argument("len"),
                value_argument("cap"),
            ),
        ),
    )

    def build(self, context: PluginBuildContext) -> ArrayLayoutState:
        unit = context.unit
        core = context.core
        assert core is not None
        ast_records = {item.name: item for item in unit.records}
        types = core.type_map()
        field_layouts: dict[str, FieldArrayLayout] = {}
        record_layouts: dict[str, RecordArrayLayout] = {}
        for record in core.records:
            ast_record = ast_records[record.name]
            core_fields = {item.name: item for item in record.fields}
            annotation = find_annotation(ast_record.annotations, "jsonStruct", ast_record.location)
            if annotation and annotation.arguments and not has_flag(annotation, "asarray"):
                raise AnnotationError(
                    "parameterized @jsonStruct requires the asarray flag",
                    ast_record.location,
                )
            if has_flag(annotation, "asarray"):
                record_layouts[record.id] = self._build_record_layout(
                    ast_record, record.fields, types, annotation
                )
            for ast_field in ast_record.fields:
                json = find_annotation(ast_field.annotations, "json", ast_field.location)
                kind = argument_value(json, "type")
                length_name = argument_value(json, "len")
                core_field = core_fields[ast_field.name]
                core_type = types[core_field.type_id]
                if kind is not None and kind != "array":
                    raise AnnotationError("the only supported @json type is 'array'", ast_field.location)
                if kind == "array":
                    if (
                        ast_field.type.kind is not AstTypeKind.POINTER
                        or ast_field.type.target is None
                        or (
                            ast_field.type.target.kind is AstTypeKind.INTEGER
                            and ast_field.type.target.name == "char"
                        )
                    ):
                        raise AnnotationError(
                            "type=array requires a non-string pointer field", ast_field.location
                        )
                    if length_name is None:
                        raise AnnotationError(
                            "a dynamic array requires len=<field>", ast_field.location
                        )
                elif length_name is not None and core_type.kind is not CoreTypeKind.FIXED_ARRAY:
                    raise AnnotationError(
                        "len is only valid for fixed or dynamic arrays", ast_field.location
                    )
                if length_name is not None:
                    length = core_fields.get(length_name)
                    if length is None:
                        raise AnnotationError(
                            f"array field {ast_field.name!r} references missing length field {length_name!r}",
                            ast_field.location,
                        )
                    self._validate_count_field(length, types, "array length")
                    field_layouts[core_field.id] = FieldArrayLayout(
                        length.id, kind == "array"
                    )
        return ArrayLayoutState(
            frozen_map(field_layouts.items()),
            frozen_map(record_layouts.items()),
        )

    def _build_record_layout(
        self,
        ast_record: AstRecord,
        fields: tuple[CoreFieldSchema, ...],
        types: dict[str, CoreTypeSchema],
        annotation: Annotation | None,
    ) -> RecordArrayLayout:
        elems_name = argument_value(annotation, "elems")
        if elems_name is None:
            raise AnnotationError("@jsonStruct(asarray) requires elems=<field>", ast_record.location)
        names = {item.name: item for item in fields}
        length_name = argument_value(annotation, "len")
        capacity_name = argument_value(annotation, "cap")
        references = [item for item in (elems_name, length_name, capacity_name) if item]
        if len(references) != len(set(references)):
            raise AnnotationError(
                "array record elems, len, and cap fields must be distinct", ast_record.location
            )
        for name in references:
            if name not in names:
                raise AnnotationError(
                    f"array record references missing field {name!r}", ast_record.location
                )
        elems = names[elems_name]
        elems_type = types[elems.type_id]
        if (
            elems_type.kind is not CoreTypeKind.POINTER
            or elems_type.target == "void"
        ):
            raise AnnotationError(
                "array record elems field must be a non-void pointer", elems.location
            )
        length = names.get(length_name) if length_name else None
        capacity = names.get(capacity_name) if capacity_name else None
        if length:
            self._validate_count_field(length, types, "array record len")
        if capacity:
            self._validate_count_field(capacity, types, "array record cap")
        storage = {item.id for item in (elems, length, capacity) if item is not None}
        return RecordArrayLayout(
            elems.id,
            elems_type.target,
            length.id if length else None,
            capacity.id if capacity else None,
            tuple(sorted(item.id for item in fields if item.id not in storage)),
        )

    def _validate_count_field(
        self, field: CoreFieldSchema, types: dict[str, CoreTypeSchema], role: str
    ) -> None:
        item = types[field.type_id]
        if (
            item.kind is not CoreTypeKind.INTEGER
            or item.signed
        ):
            raise AnnotationError(f"{role} field must be an unsigned integer", field.location)

    def validate(
        self, context: PluginValidationContext, state: ArrayLayoutState
    ) -> None:
        core = context.core
        plugins = context.states
        binding = plugins.get(BINDING_KEY)
        if binding is None:
            return
        bindings = binding.fields
        metadata = state.metadata_field_ids()
        array_records = set(state.records)
        fields = core.field_map()
        for field_id in metadata:
            if bindings[field_id].required:
                raise AnnotationError(
                    "an array length metadata field cannot be required",
                    fields[field_id].location,
                )
        for field_id, option in bindings.items():
            if not option.flatten:
                continue
            field = fields[field_id]
            if field.type_id in array_records:
                raise AnnotationError(
                    "an array-shaped record cannot be flattened", field.location
                )

    def format_state(self, state: ArrayLayoutState) -> str:
        lines = [
            f"{field_id} len={item.length_field_id} "
            f"kind={'dynamic' if item.dynamic else 'fixed'}"
            for field_id, item in state.fields.items()
        ]
        for record_id, item in state.records.items():
            parts = [
                record_id,
                f"elems={item.elems_field_id}",
                f"element={item.element_type_id}",
            ]
            if item.length_field_id:
                parts.append(f"len={item.length_field_id}")
            if item.capacity_field_id:
                parts.append(f"cap={item.capacity_field_id}")
            if item.ignored_field_ids:
                parts.append(f"ignored={item.ignored_field_ids!r}")
            lines.append(" ".join(parts))
        return "\n".join(lines)
