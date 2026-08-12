import json
import unittest
from pathlib import Path


class VSCodeExtensionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.extension = Path(__file__).parents[2] / "vscode-extension"
        cls.manifest = json.loads(
            (cls.extension / "package.json").read_text(encoding="utf-8")
        )
        cls.grammar = json.loads(
            (
                cls.extension / "syntaxes" / "jbcgen-annotations.tmLanguage.json"
            ).read_text(encoding="utf-8")
        )

    def test_manifest_injects_into_c_and_cpp_without_runtime(self) -> None:
        grammars = self.manifest["contributes"]["grammars"]
        self.assertEqual(len(grammars), 1)
        self.assertEqual(grammars[0]["injectTo"], ["source.c", "source.cpp"])
        self.assertNotIn("main", self.manifest)
        self.assertNotIn("activationEvents", self.manifest)
        self.assertNotIn("dependencies", self.manifest)

    def test_grammar_covers_document_comments_and_current_annotations(self) -> None:
        self.assertEqual(self.grammar["injectionSelector"], "L:source.c, L:source.cpp")
        repository = self.grammar["repository"]
        self.assertEqual(repository["line-documentation"]["begin"], "(?=///|//!)")
        self.assertEqual(
            repository["block-documentation"]["begin"], "(?=/\\*\\*|/\\*!)"
        )
        annotation = repository["annotation"]["match"]
        for name in (
            "jsonStruct",
            "jsonDecode",
            "jsonCleanup",
            "jsonEnum",
            "json",
        ):
            self.assertIn(name, annotation)

        argument_rules = repository["annotation-arguments"]["patterns"]
        matches = "\n".join(rule.get("match", "") for rule in argument_rules)
        for name in (
            "asarray",
            "required",
            "flatten",
            "omitempty",
            "key",
            "altkey",
            "type",
            "len",
            "elems",
            "cap",
            "min",
            "max",
            "minlen",
            "maxlen",
            "name",
        ):
            self.assertIn(name, matches)

    def test_each_document_comment_reuses_argument_rules_for_multiline_input(
        self,
    ) -> None:
        repository = self.grammar["repository"]
        for comment in ("line-documentation", "block-documentation"):
            includes = {
                pattern.get("include") for pattern in repository[comment]["patterns"]
            }
            self.assertEqual(includes, {"#annotation", "#annotation-arguments"})


if __name__ == "__main__":
    unittest.main()
