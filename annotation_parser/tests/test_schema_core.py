import unittest
from dataclasses import fields
from pathlib import Path

from annotation_parser.annotations import parse_annotations
from annotation_parser.clang_frontend import AstField, AstRecord, TranslationUnit, parse_type_spelling
from annotation_parser.diagnostics import SourceLocation
from annotation_parser.schema_core import CoreFieldSchema, build_core_schema, format_core_schema


LOCATION = SourceLocation("input.h", 1, 1)


def make_field(name: str, c_type: str, annotation: str = "") -> AstField:
    return AstField(
        f"clang-{name}",
        name,
        parse_type_spelling(c_type, record_names={"Root", "Child"}),
        parse_annotations(annotation, LOCATION),
        LOCATION,
    )


def make_unit(root_annotation: str, value_annotation: str) -> TranslationUnit:
    child = AstRecord(
        "clang-child",
        "Child",
        (make_field("number", "int"),),
        (),
        LOCATION,
    )
    root = AstRecord(
        "clang-root",
        "Root",
        (
            make_field("child", "struct Child"),
            make_field("value", "unsigned short", value_annotation),
        ),
        parse_annotations(root_annotation, LOCATION),
        LOCATION,
    )
    return TranslationUnit(Path("input.h"), (child, root), (), (), ())


class CoreSchemaTest(unittest.TestCase):
    def test_json_options_do_not_change_core(self) -> None:
        plain = build_core_schema(make_unit("@jsonStruct", ""), ("Root",), ())
        decorated = build_core_schema(
            make_unit("@jsonStruct", "@json(key=renamed, required, min=2)"),
            ("Root",),
            (),
        )
        self.assertEqual(plain, decorated)

    def test_core_contains_only_c_structure_and_stable_ids(self) -> None:
        core = build_core_schema(make_unit("@jsonStruct", "@json(required)"), ("Root",), ())
        self.assertEqual(
            {item.id for item in core.records}, {"record:Child", "record:Root"}
        )
        self.assertEqual(
            {item.id for item in core.field_map().values()},
            {"field:Child.number", "field:Root.child", "field:Root.value"},
        )
        core_field_names = {item.name for item in fields(CoreFieldSchema)}
        self.assertTrue(
            core_field_names.isdisjoint(
                {"key", "required", "flatten", "omitempty", "minimum", "owns_resources"}
            )
        )

    def test_recursive_references_and_printing_are_deterministic(self) -> None:
        root = AstRecord(
            "unstable-clang-id",
            "Root",
            (make_field("next", "struct Root *"),),
            parse_annotations("@jsonStruct", LOCATION),
            LOCATION,
        )
        unit = TranslationUnit(Path("input.h"), (root,), (), (), ())
        first = build_core_schema(unit, ("Root",), ())
        second = build_core_schema(unit, ("Root",), ())
        next_field = first.field_map()["field:Root.next"]
        self.assertEqual(first.type_map()[next_field.type_id].target, "record:Root")
        self.assertEqual(format_core_schema(first), format_core_schema(second))


if __name__ == "__main__":
    unittest.main()
