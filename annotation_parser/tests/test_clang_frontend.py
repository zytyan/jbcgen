import shutil
import tempfile
import textwrap
import unittest
from pathlib import Path

from annotation_parser.clang_frontend import ClangFrontend


@unittest.skipUnless(shutil.which("clang"), "clang is required")
class ClangFrontendTest(unittest.TestCase):
    def test_extracts_declarations_and_trailing_comment(self) -> None:
        source = textwrap.dedent(
            """
            #include <stdbool.h>
            typedef struct json_parser json_parser;
            typedef struct json_allocator json_allocator;
            /// @jsonStruct
            typedef struct Item {
              int id;
              char name[8]; /// @json(required, altkey=display-name)
            } Item;
            /// @jsonDecode
            bool decodeItem(json_parser *parser, Item *item);
            /// @jsonCleanup
            void releaseItem(json_allocator *allocator, Item *item);
            """
        )
        with tempfile.TemporaryDirectory() as directory:
            header = Path(directory) / "input.h"
            header.write_text(source, encoding="utf-8")
            unit = ClangFrontend().parse(header)
        item = next(record for record in unit.records if record.name == "Item")
        self.assertEqual(item.annotations[0].name, "jsonStruct")
        name = next(field for field in item.fields if field.name == "name")
        self.assertEqual(name.annotations[0].values("required"), (None,))
        self.assertEqual(name.annotations[0].values("altkey"), ("display-name",))
        self.assertEqual(
            {annotation.name for function in unit.functions for annotation in function.annotations},
            {"jsonDecode", "jsonCleanup"},
        )


if __name__ == "__main__":
    unittest.main()
