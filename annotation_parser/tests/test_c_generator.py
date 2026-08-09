import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from annotation_parser.c_generator import generate_c
from annotation_parser.clang_frontend import ClangFrontend
from annotation_parser.plan_ir import build_decode_plan, build_release_plan
from annotation_parser.schema_ir import build_schema_ir


ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "runtime"


HEADER = """
#ifndef GENERATED_TEST_H
#define GENERATED_TEST_H
#include "json_pull.h"
typedef enum Kind { KIND_A, KIND_B } Kind;
typedef struct Child {
  /// @json(required)
  char *label;
} Child;
/// @jsonStruct
typedef struct Root {
  /// @json(key=identifier, altkey=id, required, min=1)
  int id;
  char name[16]; /// @json(maxlen=12)
  /// @json(type=array, len=childCount, maxlen=4)
  Child *children;
  size_t childCount;
  int values[3]; /// @json(len=valueCount)
  size_t valueCount;
  Child *optional;
  Kind kind;
} Root;
/// @jsonDecode
bool decodeRoot(json_parser *parser, Root *root);
/// @jsonCleanup
void releaseRoot(json_allocator *allocator, Root *root);
#endif
"""


@unittest.skipUnless(shutil.which("clang"), "clang is required")
class CGeneratorTest(unittest.TestCase):
    def test_generated_source_compiles_as_c11(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            header = path / "model.h"
            output = path / "model_json.c"
            header.write_text(textwrap.dedent(HEADER), encoding="utf-8")
            unit = ClangFrontend().parse(header, ["-I", str(RUNTIME)])
            schema = build_schema_ir(unit)
            source = generate_c(schema, build_decode_plan(schema), build_release_plan(schema), "model.h")
            output.write_text(source, encoding="utf-8")
            process = subprocess.run(
                [
                    "clang",
                    "-std=c11",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    "-I",
                    str(RUNTIME),
                    "-I",
                    str(path),
                    "-fsyntax-only",
                    str(output),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(process.returncode, 0, process.stderr + "\n" + source)
            self.assertIn("jbc_decode_Root", source)
            self.assertIn("jbc_release_Root", source)
            self.assertIn("JSON_ERROR_OTHER_MISSING_REQUIRED_KEY", source)
            reserve = source.index("json_any_vec_reserve")
            empty_check = source.index("if (!json_array_try_end", source.index("jbc_decode_Root"))
            self.assertGreater(reserve, empty_check)


if __name__ == "__main__":
    unittest.main()
