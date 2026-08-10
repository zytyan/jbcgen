import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from annotation_parser.c_generator import generate_c
from annotation_parser.clang_frontend import ClangFrontend
from annotation_parser.generate_plan import build_generate_plan
from annotation_parser.schema import build_schema


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
            schema = build_schema(unit)
            source = generate_c(schema, build_generate_plan(schema), "model.h")
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
            self.assertIn("json_key_dispatch(&key_map", source)
            self.assertIn('{{"identifier", 10}, 0}', source)
            self.assertLess(source.index('{{"id", 2}, 0}'), source.index('{{"kind", 4}, 5}'))
            self.assertLess(source.index('{{"kind", 4}, 5}'), source.index('{{"name", 4}, 1}'))
            self.assertLess(source.index('{{"name", 4}, 1}'), source.index('{{"children", 8}, 2}'))
            self.assertLess(source.index('{{"children", 8}, 2}'), source.index('{{"identifier", 10}, 0}'))
            self.assertIn("JSON_ERROR_OTHER_MISSING_REQUIRED_KEY", source)
            pointer_check = source.index("JSON_TOKEN_LBRACE", source.index("out->optional"))
            pointer_allocation = source.index("parser->allocator->malloc", pointer_check)
            self.assertLess(pointer_check, pointer_allocation)
            reserve = source.index("json_any_vec_reserve")
            empty_check = source.index("if (!json_array_try_end", source.index("jbc_decode_Root"))
            self.assertGreater(reserve, empty_check)

    def test_array_record_and_anonymous_typedef_compile_as_c11(self) -> None:
        header_source = """
        #ifndef ARRAY_MODEL_H
        #define ARRAY_MODEL_H
        #include <stdint.h>
        #include "json_pull.h"
        /// @jsonStruct(asarray, elems=elems, cap=cap)
        typedef struct {
          char **elems;
          uint8_t cap;
          int ignored;
        } StringVec;
        /// @jsonStruct
        typedef struct Root {
          StringVec values;
          StringVec *optional;
          /// @json(required)
          StringVec *required;
          /// @json(type=array, len=numberCount)
          int *numbers;
          uint8_t numberCount;
          int fixed[300]; /// @json(len=fixedCount)
          uint8_t fixedCount;
        } Root;
        /// @jsonDecode
        bool decodeRoot(json_parser *parser, Root *root);
        /// @jsonCleanup
        void releaseRoot(json_allocator *allocator, Root *root);
        #endif
        """
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            header = path / "array_model.h"
            output = path / "array_model_json.c"
            header.write_text(textwrap.dedent(header_source), encoding="utf-8")
            unit = ClangFrontend().parse(header, ["-I", str(RUNTIME)])
            schema = build_schema(unit)
            source = generate_c(schema, build_generate_plan(schema), "array_model.h")
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
            self.assertIn("json_parser *parser, StringVec *out", source)
            self.assertNotIn("struct StringVec *out", source)
            self.assertIn("JSON_EXPECTED_ARRAY", source)
            self.assertIn("array_vec.byte_cap / sizeof(char *)", source)
            self.assertIn("_count >= (size_t)255", source)


if __name__ == "__main__":
    unittest.main()
