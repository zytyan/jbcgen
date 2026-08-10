import unittest
from dataclasses import dataclass
from pathlib import Path

from annotation_parser.annotations import Annotation, AnnotationArgument, parse_annotations
from annotation_parser.clang_frontend import AstField, AstRecord, TranslationUnit, parse_type_spelling
from annotation_parser.diagnostics import AnnotationError, SourceLocation
from annotation_parser.schema_core import build_core_schema
from annotation_parser.schema_plugins import (
    ARRAY_LAYOUT_KEY,
    BINDING_KEY,
    AnnotationArgumentSpec,
    AnnotationCommandSpec,
    AnnotationMode,
    AnnotationRegistry,
    ArrayLayoutPlugin,
    BindingPlugin,
    EntrypointsPlugin,
    PluginError,
    PluginKey,
    PluginSet,
)


LOCATION = SourceLocation("input.h", 4, 3)


@dataclass(frozen=True)
class ExampleState:
    value: int


class FakePlugin:
    def __init__(self, plugin_id: str, spec: AnnotationArgumentSpec):
        self.key = PluginKey(plugin_id, ExampleState)
        self.spec = spec

    def annotation_commands(self) -> tuple[AnnotationCommandSpec, ...]:
        return (AnnotationCommandSpec("json", (self.spec,)),)

    def format_state(self, state: object) -> str:
        return repr(state)


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
        entrypoints = EntrypointsPlugin().discover(unit)
        core = build_core_schema(unit, entrypoints.root_record_names(), ())
        binding = BindingPlugin().build(unit, core)
        arrays = ArrayLayoutPlugin().build(unit, core)
        plugins = PluginSet(((BINDING_KEY, binding), (ARRAY_LAYOUT_KEY, arrays)))
        BindingPlugin().validate(core, plugins)
        ArrayLayoutPlugin().validate(core, plugins)

        values = binding.field_map()["field:Root.values"]
        self.assertEqual(values.key, "items")
        self.assertTrue(values.required)
        dynamic = arrays.field_map()["field:Root.values"]
        self.assertTrue(dynamic.dynamic)
        self.assertEqual(dynamic.length_field_id, "field:Root.count")
        vec = arrays.record_map()["record:Vec"]
        self.assertEqual(vec.elems_field_id, "field:Vec.elems")
        self.assertEqual(vec.length_field_id, "field:Vec.len")
        self.assertEqual(vec.capacity_field_id, "field:Vec.cap")
        self.assertEqual(vec.ignored_field_ids, ("field:Vec.reserved",))


if __name__ == "__main__":
    unittest.main()
