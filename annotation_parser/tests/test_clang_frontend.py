import json
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from annotation_parser.clang_frontend import AstTypeKind, BasicType, ClangFrontend


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
            typedef unsigned long CountLong;
            typedef enum Mode { MODE_A, MODE_B } Mode;
            /// @jsonStruct
            typedef struct Types {
              Count count;
              CountLong countLong;
              long signedLong;
              long long signedLongLong;
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
        self.assertEqual(fields["count"].basic_type, BasicType.UNSIGNED_SHORT)
        self.assertEqual(fields["countLong"].basic_type, BasicType.UNSIGNED_LONG)
        self.assertEqual(fields["signedLong"].basic_type, BasicType.LONG)
        self.assertEqual(fields["signedLongLong"].basic_type, BasicType.LONG_LONG)
        self.assertEqual(fields["mode"].kind, AstTypeKind.ENUM)
        self.assertEqual(fields["mode"].name, "Mode")
        self.assertEqual(fields["next"].kind, AstTypeKind.POINTER)
        self.assertEqual(fields["next"].target.name, "Types")
        self.assertEqual(fields["samples"].kind, AstTypeKind.ARRAY)
        self.assertEqual(fields["samples"].capacity, 2)
        self.assertEqual(fields["samples"].target.kind, AstTypeKind.FLOAT)

    def test_scans_document_comments_without_clang_comment_nodes(self) -> None:
        source = textwrap.dedent(
            """
            #include <stdbool.h>
            typedef struct json_parser json_parser;
            typedef struct json_allocator json_allocator;
            /* UTF-8 before offsets: 中文 */
            /**
             * A paragraph that Clang may split into special comment nodes.
             * \n
             * @jsonStruct(
             *   asarray,
             *   elems=elems,
             *   len=len,
             * )
             */
            typedef struct Vec {
              int *elems;
              unsigned long len;
            } Vec;

            /// A leading paragraph.
            ///
            /// @jsonDecode
            bool decodeVec(json_parser *parser, Vec *value);
            """
        )
        with tempfile.TemporaryDirectory() as directory:
            header = Path(directory) / "input.h"
            header.write_text(source, encoding="utf-8")
            frontend = ClangFrontend()
            unit = frontend.parse(header)

            command = [
                "clang",
                "-x",
                "c",
                "-std=c11",
                "-fsyntax-only",
                "-Xclang",
                "-ast-dump=json",
                str(header),
            ]
            root = json.loads(
                subprocess.run(
                    command, capture_output=True, text=True, check=True
                ).stdout
            )

            def remove_comment_nodes(node: object) -> None:
                if not isinstance(node, dict):
                    return
                node["inner"] = [
                    child
                    for child in node.get("inner", ())
                    if child.get("kind")
                    not in {
                        "FullComment",
                        "ParagraphComment",
                        "TextComment",
                        "InlineCommandComment",
                    }
                ]
                for child in node.get("inner", ()):
                    remove_comment_nodes(child)

            remove_comment_nodes(root)
            unit_without_comment_ast = frontend.from_json(
                root, header, source.encode("utf-8")
            )

        for parsed_unit in (unit, unit_without_comment_ast):
            record = next(item for item in parsed_unit.records if item.name == "Vec")
            self.assertEqual(record.annotations[0].name, "jsonStruct")
            self.assertEqual(record.annotations[0].values("asarray"), (None,))
            self.assertEqual(record.annotations[0].values("elems"), ("elems",))
            self.assertEqual(record.annotations[0].values("len"), ("len",))
            function = next(
                item for item in parsed_unit.functions if item.name == "decodeVec"
            )
            self.assertEqual(function.annotations[0].name, "jsonDecode")

    def test_ignores_comment_markers_inside_c_literals(self) -> None:
        source = textwrap.dedent(
            r"""
            static const char *url = "https://example.test/// @jsonStruct";
            static const char slash = '/';
            /// @jsonStruct
            typedef struct Value {
              int field;
            } Value;
            """
        )
        with tempfile.TemporaryDirectory() as directory:
            header = Path(directory) / "input.h"
            header.write_text(source, encoding="utf-8")
            unit = ClangFrontend().parse(header)

        record = next(item for item in unit.records if item.name == "Value")
        self.assertEqual(
            [annotation.name for annotation in record.annotations], ["jsonStruct"]
        )

    def test_reads_annotations_from_included_header_source(self) -> None:
        included_source = textwrap.dedent(
            """
            #include <stdbool.h>
            typedef struct json_parser json_parser;
            typedef struct json_allocator json_allocator;

            /// @jsonStruct
            typedef struct IncludedItem {
              int identifier; /// @json(key=id, required)
            } IncludedItem;

            /// @jsonDecode
            bool decodeIncluded(json_parser *parser, IncludedItem *item);
            /// @jsonCleanup
            void cleanupIncluded(json_allocator *allocator, IncludedItem *item);
            """
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            included = root / "included.h"
            entry = root / "entry.h"
            included.write_text(included_source, encoding="utf-8")
            entry.write_text('#include "included.h"\n', encoding="utf-8")
            unit = ClangFrontend().parse(entry)

        record = next(item for item in unit.records if item.name == "IncludedItem")
        field = next(item for item in record.fields if item.name == "identifier")
        self.assertEqual(record.annotations[0].name, "jsonStruct")
        self.assertEqual(field.annotations[0].values("key"), ("id",))
        self.assertEqual(field.annotations[0].values("required"), (None,))
        self.assertEqual(Path(record.location.file), included)
        self.assertEqual(Path(field.annotations[0].location.file), included)
        self.assertEqual(
            {function.name for function in unit.functions},
            {"decodeIncluded", "cleanupIncluded"},
        )
        self.assertTrue(
            all(Path(function.location.file) == included for function in unit.functions)
        )


if __name__ == "__main__":
    unittest.main()
