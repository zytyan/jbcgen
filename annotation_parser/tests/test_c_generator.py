import hashlib
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from annotation_parser.c_generator import generate_c
from annotation_parser.clang_frontend import ClangFrontend
from annotation_parser.generate_plan import build_generate_plan, format_generate_plan
from annotation_parser.schema import build_schema

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "runtime"
GOLDEN = Path(__file__).with_name("golden")


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


def generate(schema, plan, include: str, source: str) -> str:
    return generate_c(
        schema,
        plan,
        include,
        source_header=source,
        source_sha256=hashlib.sha256(textwrap.dedent(HEADER).encode()).hexdigest(),
    )


@unittest.skipUnless(shutil.which("clang"), "clang is required")
class CGeneratorTest(unittest.TestCase):
    def test_reflection_source_and_plan_match_golden_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            header = Path(directory) / "model.h"
            header.write_text(textwrap.dedent(HEADER), encoding="utf-8")
            schema = build_schema(ClangFrontend().parse(header, ["-I", str(RUNTIME)]))
            plan = build_generate_plan(schema)

            self.assertEqual(
                generate(schema, plan, "model.h", "model.h"),
                (GOLDEN / "reflection_model.c").read_text(encoding="utf-8"),
            )
            self.assertEqual(
                format_generate_plan(plan, schema) + "\n",
                (GOLDEN / "reflection_plan.txt").read_text(encoding="utf-8"),
            )

    def test_generated_source_compiles_as_c11(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            header = path / "model.h"
            output = path / "model_json.c"
            header.write_text(textwrap.dedent(HEADER), encoding="utf-8")
            unit = ClangFrontend().parse(header, ["-I", str(RUNTIME)])
            schema = build_schema(unit)
            source = generate(schema, build_generate_plan(schema), "model.h", "model.h")
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
            self.assertIn("static const json_reflect_record jbc_record_Root", source)
            self.assertIn("static const json_reflect_type jbc_type_Root", source)
            self.assertIn('{{"identifier", sizeof("identifier") - 1}, 0}', source)
            self.assertIn(".offset = offsetof(struct Root, id)", source)
            self.assertIn("json_reflect_decode(parser, &jbc_type_Root, out)", source)
            self.assertIn(
                "json_reflect_release(allocator, &jbc_type_Root, out)", source
            )
            self.assertNotIn("jbc_decode_Root_field_id", source)
            self.assertLess(
                source.index('{{"id", sizeof("id") - 1}, 0}'),
                source.index('{{"kind", sizeof("kind") - 1}, 5}'),
            )
            self.assertLess(
                source.index('{{"kind", sizeof("kind") - 1}, 5}'),
                source.index('{{"name", sizeof("name") - 1}, 1}'),
            )
            self.assertLess(
                source.index('{{"name", sizeof("name") - 1}, 1}'),
                source.index('{{"children", sizeof("children") - 1}, 2}'),
            )
            self.assertLess(
                source.index('{{"children", sizeof("children") - 1}, 2}'),
                source.index('{{"identifier", sizeof("identifier") - 1}, 0}'),
            )
            self.assertIn(".flags = JSON_REFLECT_REQUIRED", source)

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
            source = generate_c(
                schema,
                build_generate_plan(schema),
                "array_model.h",
                source_header="array_model.h",
                source_sha256=hashlib.sha256(
                    textwrap.dedent(header_source).encode()
                ).hexdigest(),
            )
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
            self.assertIn(".size = sizeof(StringVec)", source)
            self.assertNotIn("sizeof(struct StringVec)", source)
            self.assertIn(".shape = JSON_REFLECT_ARRAY", source)
            self.assertIn(".element_type = &jbc_type_string_pointer", source)
            self.assertIn(
                ".capacity_type = JSON_REFLECT_BASIC_TYPE(((StringVec *)0)->cap)",
                source,
            )
            self.assertNotIn("jbc_type_integer_u8", source)


if __name__ == "__main__":
    unittest.main()
