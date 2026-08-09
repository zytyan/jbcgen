import unittest

from annotation_parser.annotations import parse_annotations
from annotation_parser.clang_frontend import AstField, AstRecord, AstTypedef, TranslationUnit
from annotation_parser.diagnostics import AnnotationError, SourceLocation
from annotation_parser.schema_ir import RecordShape, TypeKind, build_schema_ir, format_schema_ir


LOCATION = SourceLocation("input.h", 1, 1)


def field(name: str, c_type: str, annotation: str = "", desugared: str | None = None) -> AstField:
    return AstField(
        f"field-{name}",
        name,
        c_type,
        desugared,
        parse_annotations(annotation, LOCATION),
        LOCATION,
    )


def unit(records: tuple[AstRecord, ...]) -> TranslationUnit:
    aliases = tuple(
        AstTypedef(f"typedef-{record.name}", record.name, f"struct {record.name}", None, LOCATION)
        for record in records
    )
    return TranslationUnit(__import__("pathlib").Path("input.h"), records, aliases, (), ())


class SchemaIrTest(unittest.TestCase):
    def test_builds_recursive_reachable_schema_and_length_metadata(self) -> None:
        city = AstRecord(
            "city",
            "City",
            (field("id", "int"), field("name", "char[32]", "@json(required, maxlen=20)")),
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
        schema = build_schema_ir(unit((city, user)))
        records = schema.record_map()
        self.assertEqual(set(records), {"record:City", "record:User"})
        cities = records["record:User"].fields[0]
        count = records["record:User"].fields[1]
        self.assertEqual(schema.type_map()[cities.type_id].kind, TypeKind.DYNAMIC_ARRAY)
        self.assertTrue(cities.required)
        self.assertTrue(count.is_length_metadata)
        self.assertTrue(records["record:User"].owns_resources)
        rendered = format_schema_ir(schema)
        self.assertIn("record record:User [public, owns-resources]", rendered)
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
        with self.assertRaisesRegex(AnnotationError, "required cannot be combined with flatten"):
            build_schema_ir(unit((nested, root)))

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
            build_schema_ir(unit((nested, root)))

    def test_rejects_invalid_constraint_type(self) -> None:
        root = AstRecord(
            "root",
            "Root",
            (field("value", "int", "@json(maxlen=4)"),),
            parse_annotations("@jsonStruct", LOCATION),
            LOCATION,
        )
        with self.assertRaisesRegex(AnnotationError, "minlen/maxlen require"):
            build_schema_ir(unit((root,)))

    def test_builds_array_record_storage_variants_and_marks_ignored_fields(self) -> None:
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
                schema = build_schema_ir(unit((record,)))
                result = schema.record_map()[f"record:{name}"]
                storage = result.array_storage
                self.assertEqual(result.shape, RecordShape.ARRAY)
                self.assertIsNotNone(storage)
                assert storage is not None
                self.assertEqual(storage.elems_field, "elems")
                self.assertEqual(storage.element_type_id, "integer:i32")
                self.assertEqual(storage.length_field, "len" if "len=len" in annotation else None)
                self.assertEqual(storage.capacity_field, "cap" if "cap=cap" in annotation else None)
                self.assertTrue(next(item for item in result.fields if item.name == "reserved").ignored)
                self.assertIn("array record", format_schema_ir(schema))
                self.assertIn("[ignored]", format_schema_ir(schema))

    def test_array_record_without_count_rejects_resource_elements(self) -> None:
        record = AstRecord(
            "strings",
            "Strings",
            (field("elems", "char **"),),
            parse_annotations("@jsonStruct(asarray, elems=elems)", LOCATION),
            LOCATION,
        )
        with self.assertRaisesRegex(AnnotationError, "without len or cap"):
            build_schema_ir(unit((record,)))

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
            with self.subTest(annotation=annotation), self.assertRaisesRegex(AnnotationError, message):
                build_schema_ir(unit((record,)))

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
            build_schema_ir(unit((vector, root)))


if __name__ == "__main__":
    unittest.main()
