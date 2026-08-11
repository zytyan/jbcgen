import json
import tempfile
import unittest
from pathlib import Path

from annotation_parser.compile_commands import load_compile_command
from annotation_parser.diagnostics import FrontendError


class CompileCommandsTest(unittest.TestCase):
    def test_loads_arguments_and_removes_driver_inputs_and_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "src" / "value.c"
            source.parent.mkdir()
            database = root / "compile_commands.json"
            database.write_text(
                json.dumps(
                    [
                        {
                            "directory": str(root),
                            "file": "src/value.c",
                            "arguments": [
                                "clang",
                                "-Iinclude",
                                "-DVALUE=1",
                                "-c",
                                "src/value.c",
                                "-o",
                                "value.o",
                                "-MMD",
                                "-MFvalue.d",
                            ],
                        }
                    ]
                ),
                encoding="utf-8",
            )

            command = load_compile_command(database, source)

        self.assertEqual(command.directory, root)
        self.assertEqual(command.source, source)
        self.assertEqual(command.arguments, ("-Iinclude", "-DVALUE=1"))

    def test_accepts_directory_and_selects_nearest_source_for_header(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = root / "compile_commands.json"
            database.write_text(
                json.dumps(
                    [
                        {
                            "directory": str(root),
                            "file": "other/unrelated.c",
                            "command": "clang -DOTHER -c other/unrelated.c",
                        },
                        {
                            "directory": str(root),
                            "file": "lib/value.c",
                            "command": "clang '-DSELECTED=hello world' -c lib/value.c",
                        },
                    ]
                ),
                encoding="utf-8",
            )

            command = load_compile_command(database.parent, root / "lib" / "value.h")

        self.assertEqual(command.source, (root / "lib" / "value.c").resolve())
        self.assertEqual(command.arguments, ("-DSELECTED=hello world",))

    def test_rejects_invalid_database(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "compile_commands.json"
            database.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(FrontendError, "empty or invalid"):
                load_compile_command(database, database.parent / "value.h")


if __name__ == "__main__":
    unittest.main()
