import unittest

from annotation_parser import c_templates


class CTemplatesTest(unittest.TestCase):
    def test_generator_has_ten_complete_templates(self) -> None:
        self.assertEqual(len(c_templates.C_TEMPLATES), 10)
        self.assertEqual(len(set(c_templates.C_TEMPLATES)), 10)

    def test_renderer_rejects_missing_and_unused_values(self) -> None:
        with self.assertRaisesRegex(ValueError, "missing C template values: value"):
            c_templates.render_c_template("$value")
        with self.assertRaisesRegex(ValueError, "unused C template values: extra"):
            c_templates.render_c_template("literal", extra="value")


if __name__ == "__main__":
    unittest.main()
