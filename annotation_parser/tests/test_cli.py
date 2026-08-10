import io
import shutil
import tempfile
import textwrap
import unittest
from pathlib import Path

from annotation_parser.cli import run


ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "runtime"


@unittest.skipUnless(shutil.which("clang"), "clang is required")
class CliTest(unittest.TestCase):
    def test_generates_file_and_dumps_all_ir(self) -> None:
        header_source = textwrap.dedent(
            """
            #include "json_pull.h"
            /// @jsonStruct
            typedef struct Value {
              /// @json(required)
              int id;
            } Value;
            /// @jsonDecode
            bool decodeValue(json_parser *parser, Value *value);
            /// @jsonCleanup
            void releaseValue(json_allocator *allocator, Value *value);
            """
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            header = path / "value.h"
            output = path / "value_json.c"
            header.write_text(header_source, encoding="utf-8")
            diagnostics = io.StringIO()
            result = run(
                [
                    str(header),
                    "-o",
                    str(output),
                    "--include",
                    "value.h",
                    "--dump-ir",
                    "all",
                    "--",
                    "-I",
                    str(RUNTIME),
                ],
                diagnostics,
            )
            self.assertEqual(result, 0, diagnostics.getvalue())
            self.assertIn("SchemaIR", diagnostics.getvalue())
            self.assertIn("  core", diagnostics.getvalue())
            self.assertIn("plugin jbcgen.json.binding.v1", diagnostics.getvalue())
            self.assertIn("DecodePlan", diagnostics.getvalue())
            self.assertIn("ReleasePlan", diagnostics.getvalue())
            self.assertIn("bool decodeValue", output.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
