import shutil
import tempfile
import textwrap
import unittest
from pathlib import Path

from annotation_parser.clang_frontend import AstTypeKind, ClangFrontend


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
        self.assertEqual(name.type.kind, AstTypeKind.ARRAY)
        self.assertEqual(name.type.capacity, 8)
        self.assertEqual(name.type.target.kind, AstTypeKind.INTEGER)
        self.assertEqual(name.type.target.name, "char")
        self.assertEqual(name.annotations[0].values("required"), (None,))
        self.assertEqual(name.annotations[0].values("altkey"), ("display-name",))
        self.assertEqual(
            {
                annotation.name
                for function in unit.functions
                for annotation in function.annotations
            },
            {"jsonDecode", "jsonCleanup"},
        )
        decode = next(
            function for function in unit.functions if function.name == "decodeItem"
        )
        self.assertEqual(decode.return_type.kind, AstTypeKind.BOOL)
        self.assertEqual(decode.parameters[0].type.kind, AstTypeKind.POINTER)
        self.assertEqual(decode.parameters[0].type.target.name, "json_parser")
        self.assertEqual(decode.parameters[1].type.target.name, "Item")

    def test_extracts_named_and_anonymous_array_record_typedefs(self) -> None:
        source = textwrap.dedent(
            """
            #include <stddef.h>
            /// @jsonStruct(asarray, elems=elems, len=len)
            typedef struct NamedVec {
              int *elems;
              size_t len;
            } NamedVec;

            /// @jsonStruct(asarray, elems=elems, cap=cap)
            typedef struct {
              int *elems;
              size_t cap;
            } AnonymousVec;
            """
        )
        with tempfile.TemporaryDirectory() as directory:
            header = Path(directory) / "input.h"
            header.write_text(source, encoding="utf-8")
            unit = ClangFrontend().parse(header)

        named = next(record for record in unit.records if record.name == "NamedVec")
        anonymous = next(
            record for record in unit.records if record.name == "AnonymousVec"
        )
        self.assertEqual(named.c_type, "struct NamedVec")
        self.assertEqual(anonymous.c_type, "AnonymousVec")
        self.assertEqual(anonymous.fields[0].type.kind, AstTypeKind.POINTER)
        self.assertEqual(anonymous.fields[0].type.target.kind, AstTypeKind.INTEGER)
        self.assertEqual(anonymous.fields[1].type.kind, AstTypeKind.INTEGER)
        self.assertFalse(anonymous.fields[1].type.signed)
        self.assertEqual(named.annotations[0].values("len"), ("len",))
        self.assertEqual(anonymous.annotations[0].values("cap"), ("cap",))

    def test_resolves_typedef_enum_pointer_and_array_types_in_frontend(self) -> None:
        source = textwrap.dedent(
            """
            #include <stdint.h>
            typedef uint16_t Count;
            typedef enum Mode { MODE_A, MODE_B } Mode;
            /// @jsonStruct
            typedef struct Types {
              Count count;
              Mode mode;
              struct Types *next;
              double samples[2];
            } Types;
            """
        )
        with tempfile.TemporaryDirectory() as directory:
            header = Path(directory) / "input.h"
            header.write_text(source, encoding="utf-8")
            unit = ClangFrontend().parse(header)

        record = next(item for item in unit.records if item.name == "Types")
        fields = {field.name: field.type for field in record.fields}
        self.assertEqual(
            (fields["count"].kind, fields["count"].bits), (AstTypeKind.INTEGER, 16)
        )
        self.assertFalse(fields["count"].signed)
        self.assertEqual(fields["mode"].kind, AstTypeKind.ENUM)
        self.assertEqual(fields["mode"].name, "Mode")
        self.assertEqual(fields["next"].kind, AstTypeKind.POINTER)
        self.assertEqual(fields["next"].target.name, "Types")
        self.assertEqual(fields["samples"].kind, AstTypeKind.ARRAY)
        self.assertEqual(fields["samples"].capacity, 2)
        self.assertEqual(fields["samples"].target.kind, AstTypeKind.FLOAT)


if __name__ == "__main__":
    unittest.main()
