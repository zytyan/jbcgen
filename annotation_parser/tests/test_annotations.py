import unittest

from annotation_parser.annotations import parse_annotations
from annotation_parser.diagnostics import AnnotationError
from annotation_parser.parser import parse_annotation


class AnnotationParserTest(unittest.TestCase):
    def test_multiline_and_repeated_altkey(self) -> None:
        annotations = parse_annotations(
            """@json(
                key='display-name',
                altkey=name,
                altkey=user-name,
                required,
            )"""
        )
        self.assertEqual(annotations[0].name, "json")
        self.assertEqual(annotations[0].values("altkey"), ("name", "user-name"))
        self.assertEqual(annotations[0].values("required"), (None,))

    def test_marker_without_parentheses(self) -> None:
        parsed = parse_annotation("jsonStruct")
        self.assertEqual(parsed.function.value, "jsonStruct")
        self.assertEqual(parsed.arguments, ())

    def test_raw_and_quoted_strings(self) -> None:
        annotations = parse_annotations("@json(key=r`raw-key`, altkey=\"other\")")
        self.assertEqual(annotations[0].values("key"), ("raw-key",))
        self.assertEqual(annotations[0].values("altkey"), ("other",))

    def test_rejects_unknown_argument(self) -> None:
        with self.assertRaisesRegex(AnnotationError, "unknown @json argument"):
            parse_annotations("@json(requried)")

    def test_rejects_duplicate_single_value(self) -> None:
        with self.assertRaisesRegex(AnnotationError, "duplicate @json argument"):
            parse_annotations("@json(key=a, key=b)")

    def test_json_struct_array_arguments(self) -> None:
        annotation = parse_annotations(
            "@jsonStruct(asarray, elems=items, len=count, cap=capacity)"
        )[0]
        self.assertEqual(annotation.values("asarray"), (None,))
        self.assertEqual(annotation.values("elems"), ("items",))
        self.assertEqual(annotation.values("len"), ("count",))
        self.assertEqual(annotation.values("cap"), ("capacity",))

    def test_argumentless_json_struct_remains_valid(self) -> None:
        self.assertEqual(parse_annotations("@jsonStruct")[0].arguments, ())

    def test_rejects_incomplete_or_duplicate_json_struct_arguments(self) -> None:
        cases = (
            ("@jsonStruct(elems=items)", "requires the asarray flag"),
            ("@jsonStruct(asarray)", "requires elems"),
            ("@jsonStruct(asarray, elems=a, elems=b)", "duplicate @jsonStruct argument"),
            ("@jsonStruct(asarray=yes, elems=a)", "is a flag"),
            ("@jsonStruct(asarray, elems)", "requires a value"),
            ("@jsonStruct(asarray, elems=a, other=b)", "unknown @jsonStruct argument"),
        )
        for text, message in cases:
            with self.subTest(text=text), self.assertRaisesRegex(AnnotationError, message):
                parse_annotations(text)


if __name__ == "__main__":
    unittest.main()
