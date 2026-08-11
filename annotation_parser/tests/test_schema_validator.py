import unittest
from pathlib import Path

from annotation_parser.annotations import parse_annotations
from annotation_parser.clang_frontend import (
    AstField,
    AstRecord,
    TranslationUnit,
    parse_type_spelling,
)
from annotation_parser.diagnostics import AnnotationError, SourceLocation
from annotation_parser.schema import SchemaBuilder
from annotation_parser.schema_validator import validate_annotations, validate_schema

LOCATION = SourceLocation("validator.h", 1, 1)


def field(name: str, c_type: str, annotation: str = "") -> AstField:
    return AstField(
        name,
        name,
        parse_type_spelling(c_type, record_names={"Nested", "Root", "Strings"}),
        parse_annotations(annotation, LOCATION),
        LOCATION,
    )


def build_unvalidated(*records: AstRecord):
    unit = TranslationUnit(Path("validator.h"), records, (), (), ())
    return SchemaBuilder(unit).build()


class SchemaValidatorTest(unittest.TestCase):
    def test_annotation_contract_is_validated_before_schema_building(self) -> None:
        root = AstRecord(
            "root",
            "Root",
            (field("value", "int", "@json(requried)"),),
            parse_annotations("@jsonStruct", LOCATION),
            LOCATION,
        )
        unit = TranslationUnit(Path("validator.h"), (root,), (), (), ())
        with self.assertRaisesRegex(AnnotationError, "unknown @json argument"):
            validate_annotations(unit)

    def test_constraint_rules_are_deferred_until_validation(self) -> None:
        root = AstRecord(
            "root",
            "Root",
            (field("value", "int", "@json(maxlen=4)"),),
            parse_annotations("@jsonStruct", LOCATION),
            LOCATION,
        )
        schema = build_unvalidated(root)
        with self.assertRaisesRegex(AnnotationError, "minlen/maxlen require"):
            validate_schema(schema)

    def test_count_field_rules_are_deferred_until_validation(self) -> None:
        root = AstRecord(
            "root",
            "Root",
            (
                field("values", "int *", "@json(type=array, len=count)"),
                field("count", "int"),
            ),
            parse_annotations("@jsonStruct", LOCATION),
            LOCATION,
        )
        schema = build_unvalidated(root)
        with self.assertRaisesRegex(AnnotationError, "unsigned integer"):
            validate_schema(schema)

    def test_binding_rules_are_deferred_until_validation(self) -> None:
        nested = AstRecord("nested", "Nested", (field("value", "int"),), (), LOCATION)
        root = AstRecord(
            "root",
            "Root",
            (field("nested", "struct Nested", "@json(flatten, required)"),),
            parse_annotations("@jsonStruct", LOCATION),
            LOCATION,
        )
        schema = build_unvalidated(nested, root)
        with self.assertRaisesRegex(AnnotationError, "required.*flatten"):
            validate_schema(schema)

    def test_ownership_rules_are_deferred_until_validation(self) -> None:
        strings = AstRecord(
            "strings",
            "Strings",
            (field("elems", "char **"),),
            parse_annotations("@jsonStruct(asarray, elems=elems)", LOCATION),
            LOCATION,
        )
        schema = build_unvalidated(strings)
        with self.assertRaisesRegex(AnnotationError, "without len or cap"):
            validate_schema(schema)


if __name__ == "__main__":
    unittest.main()
