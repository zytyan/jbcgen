from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .clang_frontend import TranslationUnit
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
    PluginBuildContext,
    PluginError,
    PluginSet,
    PluginValidationContext,
    RecordShape,
    SchemaPlugin,
)


# These names remain importable for Plan/Generator consumers while their storage
# has moved out of Core Schema and into the JSON Value Types plugin.
TypeKind = JsonValueKind
TypeSchema = JsonValueType


@dataclass(frozen=True)
class SchemaIR:
    core: CoreSchemaIR
    plugins: PluginSet


def builtin_plugins() -> tuple[SchemaPlugin[Any], ...]:
    return (
        EntrypointsPlugin(),
        BindingPlugin(),
        ArrayLayoutPlugin(),
        JsonValueTypesPlugin(),
        ConstraintsPlugin(),
        OwnershipPlugin(),
        EncodeHintsPlugin(),
    )


def _validate_annotations(
    unit: TranslationUnit, plugins: tuple[SchemaPlugin[Any], ...]
) -> None:
    registry = AnnotationRegistry.from_plugins(plugins)
    annotations = []
    for record in unit.records:
        annotations.extend(record.annotations)
        for field in record.fields:
            annotations.extend(field.annotations)
    for function in unit.functions:
        annotations.extend(function.annotations)
    for annotation in annotations:
        registry.validate(annotation)


def build_schema_ir(
    unit: TranslationUnit,
    plugins: tuple[SchemaPlugin[Any], ...] | None = None,
) -> SchemaIR:
    registered = builtin_plugins() if plugins is None else plugins
    by_id: dict[str, SchemaPlugin[Any]] = {}
    for plugin in registered:
        if plugin.key.id in by_id:
            raise PluginError(f"duplicate plugin ID {plugin.key.id!r}")
        by_id[plugin.key.id] = plugin
    _validate_annotations(unit, registered)

    entry_plugin = by_id.get(ENTRYPOINTS_KEY.id)
    if entry_plugin is None or entry_plugin.key.state_type is not ENTRYPOINTS_KEY.state_type:
        raise PluginError(f"required plugin {ENTRYPOINTS_KEY.id!r} is missing")
    entrypoints = entry_plugin.build(PluginBuildContext(unit, None, PluginSet()))
    core = build_core_schema(
        unit, entrypoints.root_record_names(), entrypoints.function_names()
    )
    values: list[tuple[Any, object]] = [(ENTRYPOINTS_KEY, entrypoints)]
    complete = {ENTRYPOINTS_KEY.id}
    remaining = {
        plugin_id: plugin
        for plugin_id, plugin in by_id.items()
        if plugin_id != ENTRYPOINTS_KEY.id
    }
    while remaining:
        ready = [
            plugin
            for plugin in remaining.values()
            if all(dependency.id in complete for dependency in plugin.dependencies())
        ]
        if not ready:
            missing = sorted(
                {
                    dependency.id
                    for plugin in remaining.values()
                    for dependency in plugin.dependencies()
                    if dependency.id not in by_id
                }
            )
            if missing:
                raise PluginError(
                    "missing plugin dependencies: " + ", ".join(missing)
                )
            unresolved = ", ".join(sorted(remaining))
            raise PluginError(f"plugin dependency cycle: {unresolved}")
        plugin = min(ready, key=lambda item: item.key.id)
        states = PluginSet(tuple(values))
        state = plugin.build(PluginBuildContext(unit, core, states))
        values.append((plugin.key, state))
        complete.add(plugin.key.id)
        del remaining[plugin.key.id]

    states = PluginSet(tuple(values))
    validation = PluginValidationContext(unit, core, states)
    for plugin in sorted(registered, key=lambda item: item.key.id):
        plugin.validate(validation, states.require(plugin.key))
    return SchemaIR(core, states)


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
        formatter = formatters.get(entry.id)
        rendered = formatter(entry.state) if formatter else repr(entry.state)
        lines.extend(f"      {line}" for line in rendered.splitlines())
    return "\n".join(lines)
