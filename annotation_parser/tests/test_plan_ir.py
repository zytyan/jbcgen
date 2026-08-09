import unittest
from pathlib import Path

from annotation_parser.annotations import parse_annotations
from annotation_parser.clang_frontend import AstField, AstRecord, AstTypedef, TranslationUnit
from annotation_parser.diagnostics import SourceLocation
from annotation_parser.plan_ir import (
    DecodeOperation,
    ReleaseOperation,
    build_decode_plan,
    build_release_plan,
    format_decode_plan,
    format_release_plan,
)
from annotation_parser.schema_ir import build_schema_ir


LOCATION = SourceLocation("plan.h", 1, 1)


def field(name: str, c_type: str, annotation: str = "", desugared: str | None = None) -> AstField:
    return AstField(
        name,
        name,
        c_type,
        desugared,
        parse_annotations(annotation, LOCATION),
        LOCATION,
    )


def make_schema():
    detail = AstRecord(
        "detail",
        "Detail",
        (field("label", "char *", "@json(required)"),),
        (),
        LOCATION,
    )
    root = AstRecord(
        "root",
        "Root",
        (
            field("id", "int", "@json(key=identifier, altkey=id, required, min=1)"),
            field("detail", "struct Detail", "@json(flatten)"),
            field("items", "Detail *", "@json(type=array, len=itemCount, maxlen=8)"),
            field("itemCount", "unsigned long"),
        ),
        parse_annotations("@jsonStruct", LOCATION),
        LOCATION,
    )
    aliases = (
        AstTypedef("td-detail", "Detail", "struct Detail", None, LOCATION),
        AstTypedef("td-root", "Root", "struct Root", None, LOCATION),
    )
    unit = TranslationUnit(Path("plan.h"), (detail, root), aliases, (), ())
    return build_schema_ir(unit)


class PlanIrTest(unittest.TestCase):
    def test_decode_plan_expands_flatten_and_tracks_required(self) -> None:
        plan = build_decode_plan(make_schema())
        root = next(item for item in plan.objects if item.record_id == "record:Root")
        self.assertEqual([field.path for field in root.fields], [("id",), ("detail", "label"), ("items",)])
        self.assertEqual(root.required_seen, (0, 1))
        self.assertEqual(root.fields[0].keys, ("identifier", "id"))
        self.assertEqual(root.fields[2].value.operation, DecodeOperation.DYNAMIC_ARRAY)
        self.assertEqual(root.fields[2].length_path, ("itemCount",))
        rendered = format_decode_plan(plan)
        self.assertIn("require-seen 0, 1", rendered)
        self.assertNotIn("release-string", rendered)

    def test_release_plan_is_independent_and_owns_nested_resources(self) -> None:
        plan = build_release_plan(make_schema())
        root = next(item for item in plan.objects if item.record_id == "record:Root")
        operations = {field.operation for field in root.fields}
        self.assertEqual(operations, {ReleaseOperation.RECORD, ReleaseOperation.DYNAMIC_ARRAY})
        rendered = format_release_plan(plan)
        self.assertIn("release-record", rendered)
        self.assertIn("read-length itemCount", rendered)
        self.assertNotIn("decode-integer", rendered)

    def test_recursive_pointer_plans_do_not_expand_infinitely(self) -> None:
        node = AstRecord(
            "node",
            "Node",
            (field("next", "struct Node *"),),
            parse_annotations("@jsonStruct", LOCATION),
            LOCATION,
        )
        schema = build_schema_ir(TranslationUnit(Path("node.h"), (node,), (), (), ()))
        decode = build_decode_plan(schema)
        release = build_release_plan(schema)
        self.assertEqual(len(decode.objects), 1)
        self.assertEqual(len(release.objects), 1)
        self.assertEqual(release.objects[0].fields[0].operation, ReleaseOperation.POINTER)

    def test_array_record_plans_are_separate_and_show_storage_behavior(self) -> None:
        vector = AstRecord(
            "strings",
            "Strings",
            (
                field("elems", "char **"),
                field("cap", "unsigned short"),
                field("ignored", "int"),
            ),
            parse_annotations("@jsonStruct(asarray, elems=elems, cap=cap)", LOCATION),
            LOCATION,
        )
        schema = build_schema_ir(
            TranslationUnit(
                Path("strings.h"),
                (vector,),
                (AstTypedef("td", "Strings", "struct Strings", None, LOCATION),),
                (),
                (),
            )
        )
        decode = build_decode_plan(schema)
        release = build_release_plan(schema)

        self.assertEqual(decode.objects, ())
        self.assertEqual(len(decode.arrays), 1)
        self.assertEqual(decode.arrays[0].element.operation, DecodeOperation.STRING)
        self.assertEqual(decode.arrays[0].capacity_path, ("cap",))
        self.assertEqual(release.objects, ())
        self.assertTrue(release.arrays[0].release_elements)
        self.assertEqual(release.arrays[0].capacity_path, ("cap",))
        self.assertIn("array record record:Strings", format_decode_plan(decode))
        self.assertIn("write-capacity cap", format_decode_plan(decode))
        self.assertIn("count=cap:cap release-elements", format_release_plan(release))


if __name__ == "__main__":
    unittest.main()
