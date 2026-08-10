import unittest

from annotation_parser.annotations import parse_annotations
from annotation_parser.clang_frontend import (
    AstField,
    AstRecord,
    AstType,
    AstTypeKind,
    TranslationUnit,
    parse_type_spelling,
)
from annotation_parser.diagnostics import AnnotationError, SourceLocation
from annotation_parser.schema import RecordShape, TypeKind, build_schema, format_schema

LOCATION = SourceLocation("input.h", 1, 1)


def field(
    name: str, c_type: str, annotation: str = "", desugared: str | None = None
) -> AstField:
    return AstField(
        f"field-{name}",
        name,
        parse_type_spelling(
            c_type,
            desugared,
            record_names={"City", "Nested", "Root", "Vec", "Strings", "User"},
        ),
        parse_annotations(annotation, LOCATION),
        LOCATION,
    )


def unit(records: tuple[AstRecord, ...]) -> TranslationUnit:
    return TranslationUnit(__import__("pathlib").Path("input.h"), records, (), (), ())


class SchemaTest(unittest.TestCase):
    def test_consumes_structured_frontend_type_without_parsing_c_spelling(self) -> None:
        structured = AstType(AstTypeKind.INTEGER, "opaque_counter_alias", 16, False)
        root = AstRecord(
            "root",
            "Root",
            (AstField("value", "value", structured, (), LOCATION),),
            parse_annotations("@jsonStruct", LOCATION),
            LOCATION,
        )
        schema = build_schema(unit((root,)))
        value = schema.record_map()["record:Root"].fields[0]
        self.assertEqual(value.type_id, "integer:u16")
        self.assertEqual(value.c_type, "opaque_counter_alias")

    def test_builds_recursive_reachable_schema_and_length_metadata(self) -> None:
        city = AstRecord(
            "city",
            "City",
            (
                field("id", "int"),
                field("name", "char[32]", "@json(required, maxlen=20)"),
            ),
            (),
            LOCATION,
        )
        user = AstRecord(
            "user",
            "User",
            (
                field("cities", "City *", "@json(type=array, len=citiesLen, required)"),
                field("citiesLen", "unsigned long"),
            ),
            parse_annotations("@jsonStruct", LOCATION),
            LOCATION,
        )
        schema = build_schema(unit((city, user)))
        records = schema.record_map()
        self.assertEqual(set(records), {"record:City", "record:User"})
        cities = records["record:User"].fields[0]
        count = records["record:User"].fields[1]
        self.assertEqual(schema.type_map()[cities.type_id].kind, TypeKind.DYNAMIC_ARRAY)
        self.assertTrue(cities.required)
        self.assertIn(count.id, schema.metadata_field_ids())
        self.assertTrue(records["record:User"].owns_resources)
        rendered = format_schema(schema)
        self.assertIn("record record:User", rendered)
        self.assertIn("required", rendered)

    def test_rejects_required_flatten(self) -> None:
        nested = AstRecord("nested", "Nested", (field("value", "int"),), (), LOCATION)
        root = AstRecord(
            "root",
            "Root",
            (field("nested", "struct Nested", "@json(flatten, required)"),),
            parse_annotations("@jsonStruct", LOCATION),
            LOCATION,
        )
        with self.assertRaisesRegex(
            AnnotationError, "required cannot be combined with flatten"
        ):
            build_schema(unit((nested, root)))

    def test_rejects_flatten_key_collision(self) -> None:
        nested = AstRecord("nested", "Nested", (field("id", "int"),), (), LOCATION)
        root = AstRecord(
            "root",
            "Root",
            (field("id", "int"), field("nested", "struct Nested", "@json(flatten)")),
            parse_annotations("@jsonStruct", LOCATION),
            LOCATION,
        )
        with self.assertRaisesRegex(AnnotationError, "JSON key 'id' is shared"):
            build_schema(unit((nested, root)))

    def test_rejects_invalid_constraint_type(self) -> None:
        root = AstRecord(
            "root",
            "Root",
            (field("value", "int", "@json(maxlen=4)"),),
            parse_annotations("@jsonStruct", LOCATION),
            LOCATION,
        )
        with self.assertRaisesRegex(AnnotationError, "minlen/maxlen require"):
            build_schema(unit((root,)))

    def test_builds_array_record_storage_variants_and_marks_ignored_fields(
        self,
    ) -> None:
        annotations = (
            "@jsonStruct(asarray, elems=elems, len=len, cap=cap)",
            "@jsonStruct(asarray, elems=elems, len=len)",
            "@jsonStruct(asarray, elems=elems, cap=cap)",
            "@jsonStruct(asarray, elems=elems)",
        )
        for index, annotation in enumerate(annotations):
            name = f"Vec{index}"
            record = AstRecord(
                name,
                name,
                (
                    field("elems", "int *"),
                    field("len", "unsigned short"),
                    field("cap", "unsigned int"),
                    field("reserved", "int"),
                ),
                parse_annotations(annotation, LOCATION),
                LOCATION,
            )
            with self.subTest(annotation=annotation):
                schema = build_schema(unit((record,)))
                record_schema = schema.record_map()[f"record:{name}"]
                storage = record_schema.array
                assert storage is not None
                self.assertEqual(record_schema.shape, RecordShape.ARRAY)
                self.assertEqual(storage.elems_field_id, f"field:{name}.elems")
                self.assertEqual(storage.element_type_id, "integer:i32")
                self.assertEqual(
                    storage.length_field_id,
                    f"field:{name}.len" if "len=len" in annotation else None,
                )
                self.assertEqual(
                    storage.capacity_field_id,
                    f"field:{name}.cap" if "cap=cap" in annotation else None,
                )
                self.assertIn(f"field:{name}.reserved", storage.ignored_field_ids)
                self.assertIn("shape=array", format_schema(schema))
                self.assertIn("ignored=", format_schema(schema))

    def test_array_record_without_count_rejects_resource_elements(self) -> None:
        record = AstRecord(
            "strings",
            "Strings",
            (field("elems", "char **"),),
            parse_annotations("@jsonStruct(asarray, elems=elems)", LOCATION),
            LOCATION,
        )
        with self.assertRaisesRegex(AnnotationError, "without len or cap"):
            build_schema(unit((record,)))

    def test_rejects_invalid_array_record_storage(self) -> None:
        cases = (
            (
                (field("elems", "int *"),),
                "@jsonStruct(asarray, elems=missing)",
                "missing field",
            ),
            (
                (field("elems", "int *"),),
                "@jsonStruct(asarray, elems=elems, len=elems)",
                "must be distinct",
            ),
            (
                (field("elems", "int *"), field("len", "int")),
                "@jsonStruct(asarray, elems=elems, len=len)",
                "len field must be an unsigned integer",
            ),
            (
                (field("elems", "int"),),
                "@jsonStruct(asarray, elems=elems)",
                "must be a non-void pointer",
            ),
            (
                (field("elems", "void *"),),
                "@jsonStruct(asarray, elems=elems)",
                "must be a non-void pointer",
            ),
        )
        for fields, annotation, message in cases:
            record = AstRecord(
                "vec", "Vec", fields, parse_annotations(annotation, LOCATION), LOCATION
            )
            with (
                self.subTest(annotation=annotation),
                self.assertRaisesRegex(AnnotationError, message),
            ):
                build_schema(unit((record,)))

    def test_rejects_flattening_an_array_record(self) -> None:
        vector = AstRecord(
            "vec",
            "Vec",
            (field("elems", "int *"),),
            parse_annotations("@jsonStruct(asarray, elems=elems)", LOCATION),
            LOCATION,
        )
        root = AstRecord(
            "root",
            "Root",
            (field("values", "struct Vec", "@json(flatten)"),),
            parse_annotations("@jsonStruct", LOCATION),
            LOCATION,
        )
        with self.assertRaisesRegex(AnnotationError, "cannot be flattened"):
            build_schema(unit((vector, root)))

    def test_recursive_types_have_stable_ids_and_ownership(self) -> None:
        root = AstRecord(
            "unstable-clang-id",
            "Root",
            (field("next", "struct Root *"),),
            parse_annotations("@jsonStruct", LOCATION),
            LOCATION,
        )
        first = build_schema(unit((root,)))
        second = build_schema(unit((root,)))
        next_field = first.field_map()["field:Root.next"]
        self.assertEqual(first.type_map()[next_field.type_id].target, "record:Root")
        self.assertTrue(first.record_map()["record:Root"].owns_resources)
        self.assertEqual(first, second)
        self.assertEqual(format_schema(first), format_schema(second))

    def test_builtin_annotation_vocabulary_is_strict(self) -> None:
        cases = (
            ("@json(requried)", "unknown @json argument"),
            ("@json(key=a, key=b)", "duplicate @json argument"),
            ("@json(required=yes)", "is a flag"),
        )
        for annotation, message in cases:
            root = AstRecord(
                "root",
                "Root",
                (field("value", "int", annotation),),
                parse_annotations("@jsonStruct", LOCATION),
                LOCATION,
            )
            with (
                self.subTest(annotation=annotation),
                self.assertRaisesRegex(AnnotationError, message),
            ):
                build_schema(unit((root,)))

    def test_schema_stores_json_options_directly(self) -> None:
        root = AstRecord(
            "root",
            "Root",
            (
                field(
                    "name", "char *", "@json(required, minlen=0, maxlen=8, omitempty)"
                ),
                field("score", "int", "@json(min=1, max=9)"),
            ),
            parse_annotations("@jsonStruct", LOCATION),
            LOCATION,
        )
        schema = build_schema(unit((root,)))
        name = schema.field_map()["field:Root.name"]
        score = schema.field_map()["field:Root.score"]
        self.assertTrue(name.required)
        self.assertTrue(name.omitempty)
        self.assertTrue(name.owns_resources)
        self.assertEqual(name.max_length, 8)
        self.assertEqual(score.minimum, "1")


if __name__ == "__main__":
    unittest.main()
