from __future__ import annotations

from dataclasses import dataclass

from .clang_frontend import TranslationUnit
from .diagnostics import AnnotationError
from .schema_core import CoreSchemaIR, build_core_schema, format_core_schema
from .schema_plugins import (
    ARRAY_LAYOUT_KEY,
    BINDING_KEY,
    CONSTRAINTS_KEY,
    ENCODE_HINTS_KEY,
    ENTRYPOINTS_KEY,
    OWNERSHIP_KEY,
    VALUE_TYPES_KEY,
    AnnotationRegistry,
    ArrayLayoutPlugin,
    BindingPlugin,
    ConstraintsPlugin,
    EncodeHintsPlugin,
    EntrypointsPlugin,
    JsonValueKind,
    JsonValueType,
    JsonValueTypesPlugin,
    OwnershipPlugin,
    PluginSet,
    RecordShape,
)


# These names remain importable for Plan/Generator consumers while their storage
# has moved out of Core Schema and into the JSON Value Types plugin.
TypeKind = JsonValueKind
TypeSchema = JsonValueType


@dataclass(frozen=True)
class SchemaIR:
    core: CoreSchemaIR
    plugins: PluginSet


def _builtin_plugins() -> tuple[object, ...]:
    return (
        EntrypointsPlugin(),
        BindingPlugin(),
        ArrayLayoutPlugin(),
        JsonValueTypesPlugin(),
        ConstraintsPlugin(),
        OwnershipPlugin(),
        EncodeHintsPlugin(),
    )


def _validate_annotations(unit: TranslationUnit, plugins: tuple[object, ...]) -> None:
    registry = AnnotationRegistry.from_plugins(plugins)  # type: ignore[arg-type]
    annotations = []
    for record in unit.records:
        annotations.extend(record.annotations)
        for field in record.fields:
            annotations.extend(field.annotations)
    for function in unit.functions:
        annotations.extend(function.annotations)
    for annotation in annotations:
        registry.validate(annotation)


def build_schema_ir(unit: TranslationUnit) -> SchemaIR:
    builtin = _builtin_plugins()
    _validate_annotations(unit, builtin)

    entry_plugin = builtin[0]
    assert isinstance(entry_plugin, EntrypointsPlugin)
    entrypoints = entry_plugin.discover(unit)
    core = build_core_schema(
        unit, entrypoints.root_record_names(), entrypoints.function_names()
    )

    binding_plugin = builtin[1]
    array_plugin = builtin[2]
    value_plugin = builtin[3]
    constraints_plugin = builtin[4]
    ownership_plugin = builtin[5]
    encode_plugin = builtin[6]
    assert isinstance(binding_plugin, BindingPlugin)
    assert isinstance(array_plugin, ArrayLayoutPlugin)
    assert isinstance(value_plugin, JsonValueTypesPlugin)
    assert isinstance(constraints_plugin, ConstraintsPlugin)
    assert isinstance(ownership_plugin, OwnershipPlugin)
    assert isinstance(encode_plugin, EncodeHintsPlugin)

    binding = binding_plugin.build(unit, core)
    arrays = array_plugin.build(unit, core)
    partial = PluginSet(
        ((ENTRYPOINTS_KEY, entrypoints), (BINDING_KEY, binding), (ARRAY_LAYOUT_KEY, arrays))
    )
    values = value_plugin.build(core, partial)
    with_values = PluginSet(
        (
            (ENTRYPOINTS_KEY, entrypoints),
            (BINDING_KEY, binding),
            (ARRAY_LAYOUT_KEY, arrays),
            (VALUE_TYPES_KEY, values),
        )
    )
    constraints = constraints_plugin.build(unit, core, with_values)
    ownership = ownership_plugin.build(core, with_values)
    encode_hints = encode_plugin.build(unit, core)
    plugins = PluginSet(
        (
            (ENTRYPOINTS_KEY, entrypoints),
            (BINDING_KEY, binding),
            (ARRAY_LAYOUT_KEY, arrays),
            (VALUE_TYPES_KEY, values),
            (CONSTRAINTS_KEY, constraints),
            (OWNERSHIP_KEY, ownership),
            (ENCODE_HINTS_KEY, encode_hints),
        )
    )

    entry_plugin.validate(unit, entrypoints)
    binding_plugin.validate(core, plugins)
    array_plugin.validate(core, plugins)
    _validate_cross_plugin_rules(unit, core, plugins)
    return SchemaIR(core, plugins)


def _validate_cross_plugin_rules(
    unit: TranslationUnit, core: CoreSchemaIR, plugins: PluginSet
) -> None:
    bindings = plugins.require(BINDING_KEY).field_map()
    arrays = plugins.require(ARRAY_LAYOUT_KEY).field_map()
    constraints = plugins.require(CONSTRAINTS_KEY).field_map()
    fields = core.field_map()
    for binding in bindings.values():
        if not binding.flatten:
            continue
        field = fields[binding.field_id]
        if binding.explicit_key or binding.field_id in arrays or binding.field_id in constraints:
            raise AnnotationError(
                "flatten cannot be combined with key, len, or constraints", field.location
            )


def format_schema_ir(schema: SchemaIR) -> str:
    formatters = {
        ENTRYPOINTS_KEY.id: EntrypointsPlugin().format_state,
        BINDING_KEY.id: BindingPlugin().format_state,
        ARRAY_LAYOUT_KEY.id: ArrayLayoutPlugin().format_state,
        VALUE_TYPES_KEY.id: JsonValueTypesPlugin().format_state,
        CONSTRAINTS_KEY.id: ConstraintsPlugin().format_state,
        OWNERSHIP_KEY.id: OwnershipPlugin().format_state,
        ENCODE_HINTS_KEY.id: EncodeHintsPlugin().format_state,
    }
    lines = ["SchemaIR"]
    lines.extend(f"  {line}" for line in format_core_schema(schema.core).splitlines())
    lines.append("  plugins")
    for entry in schema.plugins.entries:
        lines.append(f"    plugin {entry.id}")
        rendered = formatters[entry.id](entry.state)
        lines.extend(f"      {line}" for line in rendered.splitlines())
    return "\n".join(lines)
