import unittest
from dataclasses import dataclass
from pathlib import Path

from annotation_parser.annotations import Annotation, AnnotationArgument, parse_annotations
from annotation_parser.clang_frontend import AstField, AstRecord, TranslationUnit, parse_type_spelling
from annotation_parser.diagnostics import AnnotationError, SourceLocation
from annotation_parser.schema_core import build_core_schema
from annotation_parser.schema_ir import builtin_plugins, build_schema_ir, format_schema_ir
from annotation_parser.schema_plugins import (
    ARRAY_LAYOUT_KEY,
    BINDING_KEY,
    CONSTRAINTS_KEY,
    ENCODE_HINTS_KEY,
    ENTRYPOINTS_KEY,
    OWNERSHIP_KEY,
    VALUE_TYPES_KEY,
    AnnotationArgumentSpec,
    AnnotationCommandSpec,
    AnnotationMode,
    AnnotationRegistry,
    ArrayLayoutPlugin,
    BindingPlugin,
    EntrypointsPlugin,
    PluginError,
    PluginBuildContext,
    PluginKey,
    PluginSet,
    PluginValidationContext,
)


LOCATION = SourceLocation("input.h", 4, 3)


@dataclass(frozen=True)
class ExampleState:
    value: int


class FakePlugin:
    def __init__(self, plugin_id: str, spec: AnnotationArgumentSpec):
        self.key = PluginKey(plugin_id, ExampleState)
        self.annotation_commands = (AnnotationCommandSpec("json", (spec,)),)

    def format_state(self, state: object) -> str:
        return repr(state)


@dataclass(frozen=True)
class ExtensionState:
    field_ids: tuple[str, ...]


EXTENSION_KEY = PluginKey("example.extension.v1", ExtensionState)


class ExtensionPlugin:
    key = EXTENSION_KEY
    annotation_commands: tuple[AnnotationCommandSpec, ...] = ()
    dependencies = (BINDING_KEY,)

    def build(self, context: PluginBuildContext) -> ExtensionState:
        binding = context.states.require(BINDING_KEY)
        return ExtensionState(tuple(binding.fields))

    def validate(
        self, context: PluginValidationContext, state: ExtensionState
    ) -> None:
        if context.core is None or not state.field_ids:
            raise AssertionError("extension received an incomplete build context")

    def format_state(self, state: ExtensionState) -> str:
        return "\n".join(state.field_ids)


def make_field(name: str, c_type: str, annotation: str = "") -> AstField:
    return AstField(
        f"clang-{name}",
        name,
        parse_type_spelling(c_type, record_names={"Root", "Vec"}),
        parse_annotations(annotation, LOCATION),
        LOCATION,
    )


class PluginFrameworkTest(unittest.TestCase):
    def test_typed_plugin_set(self) -> None:
        key = PluginKey("example", ExampleState)
        state = ExampleState(7)
        plugins = PluginSet(((key, state),))
        self.assertIs(plugins.get(key), state)
        self.assertIs(plugins.require(key), state)
        self.assertIsNone(plugins.get(PluginKey("missing", ExampleState)))
        with self.assertRaisesRegex(PluginError, "required plugin.*missing"):
            plugins.require(PluginKey("missing", ExampleState))
        with self.assertRaisesRegex(PluginError, "requires state"):
            PluginSet(((key, "wrong"),))
        with self.assertRaisesRegex(PluginError, "duplicate plugin ID"):
            PluginSet(((key, state), (key, state)))

    def test_annotation_registry_merges_and_validates_plugin_vocabulary(self) -> None:
        repeated = FakePlugin(
            "repeat", AnnotationArgumentSpec("altkey", AnnotationMode.VALUE, True)
        )
        required = FakePlugin(
            "required", AnnotationArgumentSpec("required", AnnotationMode.FLAG)
        )
        registry = AnnotationRegistry.from_plugins((repeated, required))
        registry.validate(
            Annotation(
                "json",
                (
                    AnnotationArgument("altkey", "old"),
                    AnnotationArgument("altkey", "legacy"),
                    AnnotationArgument("required", None),
                ),
                LOCATION,
            )
        )
        cases = (
            (Annotation("unknown", (), LOCATION), "unknown annotation"),
            (Annotation("json", (AnnotationArgument("nope", None),), LOCATION), "unknown @json"),
            (Annotation("json", (AnnotationArgument("required", "yes"),), LOCATION), "is a flag"),
            (Annotation("json", (AnnotationArgument("altkey", None),), LOCATION), "requires a value"),
            (
                Annotation(
                    "json",
                    (AnnotationArgument("required", None), AnnotationArgument("required", None)),
                    LOCATION,
                ),
                "duplicate @json",
            ),
        )
        for annotation, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(AnnotationError, message):
                registry.validate(annotation)

    def test_annotation_registry_rejects_conflicting_declarations(self) -> None:
        first = FakePlugin("first", AnnotationArgumentSpec("option", AnnotationMode.FLAG))
        second = FakePlugin("second", AnnotationArgumentSpec("option", AnnotationMode.VALUE))
        with self.assertRaisesRegex(PluginError, "declared incompatibly"):
            AnnotationRegistry.from_plugins((first, second))


class BuiltinPluginTest(unittest.TestCase):
    def test_binding_and_array_layout_are_separate_states(self) -> None:
        vector = AstRecord(
            "clang-vec",
            "Vec",
            (
                make_field("elems", "int *"),
                make_field("len", "unsigned short"),
                make_field("cap", "unsigned int"),
                make_field("reserved", "int"),
            ),
            parse_annotations(
                "@jsonStruct(asarray, elems=elems, len=len, cap=cap)", LOCATION
            ),
            LOCATION,
        )
        root = AstRecord(
            "clang-root",
            "Root",
            (
                make_field("values", "int *", "@json(type=array, len=count, key=items, required)"),
                make_field("count", "unsigned long"),
                make_field("vector", "struct Vec"),
            ),
            parse_annotations("@jsonStruct", LOCATION),
            LOCATION,
        )
        unit = TranslationUnit(Path("input.h"), (vector, root), (), (), ())
        entrypoints = EntrypointsPlugin().build(PluginBuildContext(unit, None, PluginSet()))
        core = build_core_schema(unit, entrypoints.root_record_names(), ())
        empty = PluginSet()
        binding = BindingPlugin().build(PluginBuildContext(unit, core, empty))
        arrays = ArrayLayoutPlugin().build(PluginBuildContext(unit, core, empty))
        plugins = PluginSet(((BINDING_KEY, binding), (ARRAY_LAYOUT_KEY, arrays)))
        validation = PluginValidationContext(unit, core, plugins)
        BindingPlugin().validate(validation, binding)
        ArrayLayoutPlugin().validate(validation, arrays)

        values = binding.fields["field:Root.values"]
        self.assertEqual(values.key, "items")
        self.assertTrue(values.required)
        dynamic = arrays.fields["field:Root.values"]
        self.assertTrue(dynamic.dynamic)
        self.assertEqual(dynamic.length_field_id, "field:Root.count")
        vec = arrays.records["record:Vec"]
        self.assertEqual(vec.elems_field_id, "field:Vec.elems")
        self.assertEqual(vec.length_field_id, "field:Vec.len")
        self.assertEqual(vec.capacity_field_id, "field:Vec.cap")
        self.assertEqual(vec.ignored_field_ids, ("field:Vec.reserved",))

    def test_all_builtin_states_are_independent_and_dumped_by_plugin_id(self) -> None:
        root = AstRecord(
            "clang-root",
            "Root",
            (
                make_field("name", "char *", "@json(required, minlen=0, maxlen=8, omitempty)"),
                make_field("score", "int", "@json(min=1, max=9)"),
            ),
            parse_annotations("@jsonStruct", LOCATION),
            LOCATION,
        )
        unit = TranslationUnit(Path("input.h"), (root,), (), (), ())
        schema = build_schema_ir(unit)
        ids = tuple(schema.plugins.states)
        self.assertEqual(ids, tuple(sorted(ids)))
        self.assertEqual(
            set(ids),
            {
                ENTRYPOINTS_KEY.id,
                BINDING_KEY.id,
                ARRAY_LAYOUT_KEY.id,
                VALUE_TYPES_KEY.id,
                CONSTRAINTS_KEY.id,
                OWNERSHIP_KEY.id,
                ENCODE_HINTS_KEY.id,
            },
        )
        self.assertEqual(
            schema.plugins.require(ENCODE_HINTS_KEY).omitempty_field_ids,
            ("field:Root.name",),
        )
        self.assertTrue(
            schema.plugins.require(OWNERSHIP_KEY).fields["field:Root.name"]
        )
        constraint = schema.plugins.require(CONSTRAINTS_KEY).fields
        self.assertEqual(constraint["field:Root.name"].max_length, 8)
        self.assertEqual(constraint["field:Root.score"].minimum, "1")
        rendered = format_schema_ir(schema)
        self.assertTrue(rendered.startswith("SchemaIR\n  core\n"))
        offsets = [rendered.index(f"plugin {plugin_id}") for plugin_id in ids]
        self.assertEqual(offsets, sorted(offsets))

    def test_custom_plugin_uses_declared_dependency_and_stable_core_ids(self) -> None:
        root = AstRecord(
            "clang-root",
            "Root",
            (make_field("value", "int"),),
            parse_annotations("@jsonStruct", LOCATION),
            LOCATION,
        )
        unit = TranslationUnit(Path("input.h"), (root,), (), (), ())
        schema = build_schema_ir(unit, (*builtin_plugins(), ExtensionPlugin()))
        self.assertEqual(
            schema.plugins.require(EXTENSION_KEY).field_ids, ("field:Root.value",)
        )
        self.assertIn("plugin example.extension.v1", format_schema_ir(schema))
        with self.assertRaisesRegex(PluginError, "missing plugin dependencies"):
            build_schema_ir(unit, (EntrypointsPlugin(), ExtensionPlugin()))

    def test_builtin_registry_owns_annotation_semantics(self) -> None:
        cases = (
            ("@json(requried)", "unknown @json argument"),
            ("@json(key=a, key=b)", "duplicate @json argument"),
            ("@json(required=yes)", "is a flag"),
        )
        for annotation, message in cases:
            root = AstRecord(
                "clang-root",
                "Root",
                (make_field("value", "int", annotation),),
                parse_annotations("@jsonStruct", LOCATION),
                LOCATION,
            )
            with self.subTest(annotation=annotation), self.assertRaisesRegex(
                AnnotationError, message
            ):
                build_schema_ir(
                    TranslationUnit(Path("input.h"), (root,), (), (), ())
                )


if __name__ == "__main__":
    unittest.main()
