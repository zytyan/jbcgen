from __future__ import annotations

from dataclasses import dataclass

from ..annotations import Annotation
from ..clang_frontend import AstField, AstRecord, AstTypeKind, TranslationUnit
from ..diagnostics import AnnotationError, SourceLocation
from ..schema_core import CoreFieldSchema, CoreTypeKind, CoreTypeSchema
from .base import (
    AnnotationArgumentSpec,
    AnnotationCommandSpec,
    AnnotationMode,
    PluginBuildContext,
    PluginKey,
    PluginValidationContext,
)


def _annotation(
    annotations: tuple[Annotation, ...], name: str, location: SourceLocation
) -> Annotation | None:
    selected = [item for item in annotations if item.name == name]
    if len(selected) > 1:
        raise AnnotationError(f"a declaration may contain only one @{name} annotation", location)
    return selected[0] if selected else None


def _one(annotation: Annotation | None, name: str) -> str | None:
    if annotation is None:
        return None
    values = annotation.values(name)
    return values[0] if values else None


def _flag(annotation: Annotation | None, name: str) -> bool:
    return bool(annotation and annotation.values(name))


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


class EntrypointsPlugin:
    key = ENTRYPOINTS_KEY

    def annotation_commands(self) -> tuple[AnnotationCommandSpec, ...]:
        return (
            AnnotationCommandSpec("jsonStruct"),
            AnnotationCommandSpec("jsonDecode"),
            AnnotationCommandSpec("jsonCleanup"),
        )

    def dependencies(self) -> tuple[PluginKey[object], ...]:
        return ()

    def build(self, context: PluginBuildContext) -> EntrypointsState:
        return self.discover(context.unit)

    def discover(self, unit: TranslationUnit) -> EntrypointsState:
        public_records: list[str] = []
        for record in unit.records:
            if _annotation(record.annotations, "jsonStruct", record.location) is not None:
                public_records.append(f"record:{record.name}")

        functions: list[FunctionEntrypoint] = []
        records = {record.name for record in unit.records}
        for function in unit.functions:
            for role in ("jsonDecode", "jsonCleanup"):
                if _annotation(function.annotations, role, function.location) is None:
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
    field_id: str
    key: str
    altkeys: tuple[str, ...]
    required: bool
    flatten: bool
    explicit_key: bool


@dataclass(frozen=True)
class BindingState:
    fields: tuple[FieldBinding, ...]

    def field_map(self) -> dict[str, FieldBinding]:
        return {item.field_id: item for item in self.fields}


BINDING_KEY = PluginKey("jbcgen.json.binding.v1", BindingState)


class BindingPlugin:
    key = BINDING_KEY

    def annotation_commands(self) -> tuple[AnnotationCommandSpec, ...]:
        return (
            AnnotationCommandSpec(
                "json",
                (
                    AnnotationArgumentSpec("key", AnnotationMode.VALUE),
                    AnnotationArgumentSpec("altkey", AnnotationMode.VALUE, repeatable=True),
                    AnnotationArgumentSpec("required", AnnotationMode.FLAG),
                    AnnotationArgumentSpec("flatten", AnnotationMode.FLAG),
                ),
            ),
        )

    def dependencies(self) -> tuple[PluginKey[object], ...]:
        return ()

    def build(self, context: PluginBuildContext) -> BindingState:
        unit = context.unit
        core = context.core
        assert core is not None
        ast_records = {item.name: item for item in unit.records}
        bindings: list[FieldBinding] = []
        for record in core.records:
            ast_fields = {item.name: item for item in ast_records[record.name].fields}
            for field in record.fields:
                ast_field = ast_fields[field.name]
                annotation = _annotation(ast_field.annotations, "json", ast_field.location)
                altkeys = tuple(
                    value for value in (annotation.values("altkey") if annotation else ())
                    if value is not None
                )
                bindings.append(
                    FieldBinding(
                        field.id,
                        _one(annotation, "key") or field.name,
                        altkeys,
                        _flag(annotation, "required"),
                        _flag(annotation, "flatten"),
                        _one(annotation, "key") is not None,
                    )
                )
        return BindingState(tuple(sorted(bindings, key=lambda item: item.field_id)))

    def validate(
        self, context: PluginValidationContext, state: BindingState
    ) -> None:
        # Imported lazily because Value/Constraints plugins derive from the
        # structural states defined in this module.
        from .semantics import CONSTRAINTS_KEY

        core = context.core
        plugins = context.states
        bindings = state.field_map()
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
            {item.record_id for item in array_layout.records} if array_layout else set()
        )
        metadata = array_layout.metadata_field_ids() if array_layout else frozenset()
        ignored = (
            {field_id for item in array_layout.records for field_id in item.ignored_field_ids}
            if array_layout
            else set()
        )
        constraint_state = plugins.get(CONSTRAINTS_KEY)
        constraints = constraint_state.field_map() if constraint_state else {}
        array_fields = array_layout.field_map() if array_layout else {}
        for binding in bindings.values():
            if not binding.flatten:
                continue
            field = core.field_map()[binding.field_id]
            if (
                binding.explicit_key
                or binding.field_id in array_fields
                or binding.field_id in constraints
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
        for item in state.fields:
            flags = []
            if item.required:
                flags.append("required")
            if item.flatten:
                flags.append("flatten")
            suffix = f" [{' '.join(flags)}]" if flags else ""
            aliases = f" altkeys={item.altkeys!r}" if item.altkeys else ""
            lines.append(f"{item.field_id} key={item.key!r}{aliases}{suffix}")
        return "\n".join(lines)


@dataclass(frozen=True)
class FieldArrayLayout:
    field_id: str
    length_field_id: str
    dynamic: bool


@dataclass(frozen=True)
class RecordArrayLayout:
    record_id: str
    elems_field_id: str
    element_type_id: str
    length_field_id: str | None
    capacity_field_id: str | None
    ignored_field_ids: tuple[str, ...]


@dataclass(frozen=True)
class ArrayLayoutState:
    fields: tuple[FieldArrayLayout, ...]
    records: tuple[RecordArrayLayout, ...]

    def field_map(self) -> dict[str, FieldArrayLayout]:
        return {item.field_id: item for item in self.fields}

    def record_map(self) -> dict[str, RecordArrayLayout]:
        return {item.record_id: item for item in self.records}

    def metadata_field_ids(self) -> frozenset[str]:
        return frozenset(item.length_field_id for item in self.fields)


ARRAY_LAYOUT_KEY = PluginKey("jbcgen.json.array-layout.v1", ArrayLayoutState)


class ArrayLayoutPlugin:
    key = ARRAY_LAYOUT_KEY

    def annotation_commands(self) -> tuple[AnnotationCommandSpec, ...]:
        return (
            AnnotationCommandSpec(
                "json",
                (
                    AnnotationArgumentSpec("type", AnnotationMode.VALUE),
                    AnnotationArgumentSpec("len", AnnotationMode.VALUE),
                ),
            ),
            AnnotationCommandSpec(
                "jsonStruct",
                (
                    AnnotationArgumentSpec("asarray", AnnotationMode.FLAG),
                    AnnotationArgumentSpec("elems", AnnotationMode.VALUE),
                    AnnotationArgumentSpec("len", AnnotationMode.VALUE),
                    AnnotationArgumentSpec("cap", AnnotationMode.VALUE),
                ),
            ),
        )

    def dependencies(self) -> tuple[PluginKey[object], ...]:
        return ()

    def build(self, context: PluginBuildContext) -> ArrayLayoutState:
        unit = context.unit
        core = context.core
        assert core is not None
        ast_records = {item.name: item for item in unit.records}
        types = core.type_map()
        field_layouts: list[FieldArrayLayout] = []
        record_layouts: list[RecordArrayLayout] = []
        for record in core.records:
            ast_record = ast_records[record.name]
            core_fields = {item.name: item for item in record.fields}
            annotation = _annotation(ast_record.annotations, "jsonStruct", ast_record.location)
            if annotation and annotation.arguments and not _flag(annotation, "asarray"):
                raise AnnotationError(
                    "parameterized @jsonStruct requires the asarray flag",
                    ast_record.location,
                )
            if _flag(annotation, "asarray"):
                record_layouts.append(
                    self._build_record_layout(ast_record, record.fields, types, annotation)
                )
            for ast_field in ast_record.fields:
                json = _annotation(ast_field.annotations, "json", ast_field.location)
                kind = _one(json, "type")
                length_name = _one(json, "len")
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
                    field_layouts.append(
                        FieldArrayLayout(core_field.id, length.id, kind == "array")
                    )
        return ArrayLayoutState(
            tuple(sorted(field_layouts, key=lambda item: item.field_id)),
            tuple(sorted(record_layouts, key=lambda item: item.record_id)),
        )

    def _build_record_layout(
        self,
        ast_record: AstRecord,
        fields: tuple[CoreFieldSchema, ...],
        types: dict[str, CoreTypeSchema],
        annotation: Annotation | None,
    ) -> RecordArrayLayout:
        elems_name = _one(annotation, "elems")
        if elems_name is None:
            raise AnnotationError("@jsonStruct(asarray) requires elems=<field>", ast_record.location)
        names = {item.name: item for item in fields}
        length_name = _one(annotation, "len")
        capacity_name = _one(annotation, "cap")
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
            f"record:{ast_record.name}",
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
        bindings = binding.field_map()
        metadata = state.metadata_field_ids()
        array_records = set(state.record_map())
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
            f"{item.field_id} len={item.length_field_id} "
            f"kind={'dynamic' if item.dynamic else 'fixed'}"
            for item in state.fields
        ]
        for item in state.records:
            parts = [
                f"{item.record_id}",
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
