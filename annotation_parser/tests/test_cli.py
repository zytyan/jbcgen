import hashlib
import io
import json
import shutil
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

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
            self.assertIn("Schema\n", diagnostics.getvalue())
            self.assertIn("GeneratePlan", diagnostics.getvalue())
            generated = output.read_text(encoding="utf-8")
            self.assertIn("bool decodeValue", generated)
            self.assertIn(f" * Source: {header}", generated)
            self.assertIn(
                f" * Source SHA-256: {hashlib.sha256(header.read_bytes()).hexdigest()}",
                generated,
            )

            with patch("annotation_parser.cli._atomic_write") as atomic_write:
                result = run(
                    [
                        str(header),
                        "-o",
                        str(output),
                        "--include",
                        "value.h",
                        "--",
                        "-I",
                        str(RUNTIME),
                    ],
                    diagnostics,
                )
                self.assertEqual(result, 0, diagnostics.getvalue())
                atomic_write.assert_not_called()

    def test_uses_compile_commands_arguments_and_working_directory(self) -> None:
        header_source = textwrap.dedent(
            """
            #include "json_pull.h"
            /// @jsonStruct
            typedef struct Value { int id; } Value;
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
            relative_runtime = Path("runtime")
            (path / relative_runtime).symlink_to(RUNTIME, target_is_directory=True)
            (path / "compile_commands.json").write_text(
                json.dumps(
                    [
                        {
                            "directory": str(path),
                            "file": "value.h",
                            "arguments": [
                                "clang",
                                "-I",
                                str(relative_runtime),
                                "-c",
                                "value.h",
                                "-o",
                                "value.o",
                            ],
                        }
                    ]
                ),
                encoding="utf-8",
            )

            diagnostics = io.StringIO()
            result = run(
                [
                    str(header),
                    "-o",
                    str(output),
                    "-c",
                    str(path),
                ],
                diagnostics,
            )

            self.assertEqual(result, 0, diagnostics.getvalue())
            self.assertIn("bool decodeValue", output.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
