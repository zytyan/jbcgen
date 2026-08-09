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


if __name__ == "__main__":
    unittest.main()
