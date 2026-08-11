import unittest
from pathlib import Path

from annotation_parser.annotations import parse_annotations
from annotation_parser.clang_frontend import (
    AstField,
    AstRecord,
    TranslationUnit,
    parse_type_spelling,
)
from annotation_parser.diagnostics import SourceLocation
from annotation_parser.generate_plan import build_generate_plan, format_generate_plan
from annotation_parser.schema import RecordShape, TypeKind, build_schema

LOCATION = SourceLocation("plan.h", 1, 1)


def field(
    name: str, c_type: str, annotation: str = "", desugared: str | None = None
) -> AstField:
    return AstField(
        name,
        name,
        parse_type_spelling(
            c_type,
            desugared,
            record_names={"Detail", "Root", "Node", "Strings"},
        ),
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
    return build_schema(TranslationUnit(Path("plan.h"), (detail, root), (), (), ()))


class GeneratePlanTest(unittest.TestCase):
    def test_object_plan_expands_flatten_and_links_rollback(self) -> None:
        schema = make_schema()
        plan = build_generate_plan(schema)
        root = plan.type_map()["record:Root"]
        self.assertEqual(
            [field.path for field in root.fields],
            [("id",), ("detail", "label"), ("items",)],
        )
        self.assertEqual([field.field_index for field in root.fields], [0, 1, 2])
        self.assertEqual(root.type_descriptor, "jbc_type_Root")
        self.assertEqual(root.record_descriptor, "jbc_record_Root")
        self.assertEqual(
            [(item.key, item.field_index) for item in root.key_entries],
            [("id", 0), ("items", 2), ("label", 1), ("identifier", 0)],
        )
        self.assertEqual(root.fields[2].length_path, ("itemCount",))
        self.assertEqual(
            schema.type_map()[schema.field_map()[root.fields[2].field_id].type_id].kind,
            TypeKind.DYNAMIC_ARRAY,
        )
        self.assertEqual(
            root.owned_field_ids,
            ("field:Root.detail", "field:Root.items"),
        )
        rendered = format_generate_plan(plan, schema)
        self.assertIn("decode-failure -> json_reflect_release(self)", rendered)
        self.assertIn("field detail.label", rendered)
        self.assertIn("release-storage", rendered)

    def test_key_entries_use_utf8_length_then_byte_order(self) -> None:
        schema = make_schema()
        root = build_generate_plan(schema).type_map()["record:Root"]
        keys = [item.key for item in root.key_entries]
        self.assertEqual(
            keys, sorted(keys, key=lambda key: (len(key.encode()), key.encode()))
        )

    def test_recursive_pointer_plan_does_not_expand_infinitely(self) -> None:
        node = AstRecord(
            "node",
            "Node",
            (field("next", "struct Node *"),),
            parse_annotations("@jsonStruct", LOCATION),
            LOCATION,
        )
        schema = build_schema(TranslationUnit(Path("node.h"), (node,), (), (), ()))
        plan = build_generate_plan(schema)
        self.assertEqual(len(plan.types), 1)
        node_plan = plan.types[0]
        self.assertEqual(node_plan.owned_field_ids, ("field:Node.next",))
        self.assertEqual(node_plan.dependencies, ())

    def test_array_record_uses_one_type_plan_for_decode_and_release(self) -> None:
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
        schema = build_schema(TranslationUnit(Path("strings.h"), (vector,), (), (), ()))
        plan = build_generate_plan(schema)
        item = plan.type_map()["record:Strings"]
        self.assertEqual(item.shape, RecordShape.ARRAY)
        self.assertEqual(item.fields, ())
        self.assertEqual(item.type_descriptor, "jbc_type_Strings")
        storage = schema.record_map()[item.record_id].array
        assert storage is not None
        self.assertEqual(storage.element_type_id, "string:pointer")
        self.assertEqual(storage.capacity_field_id, "field:Strings.cap")
        rendered = format_generate_plan(plan, schema)
        self.assertIn("shape=array", rendered)
        self.assertIn("write-capacity=field:Strings.cap", rendered)


if __name__ == "__main__":
    unittest.main()
