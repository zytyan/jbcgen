from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from .annotations import Annotation, parse_annotations
from .diagnostics import FrontendError, SourceLocation


class AstTypeKind(Enum):
    VOID = "void"
    BOOL = "bool"
    INTEGER = "integer"
    FLOAT = "float"
    ENUM = "enum"
    RECORD = "record"
    POINTER = "pointer"
    ARRAY = "array"
    UNKNOWN = "unknown"


class BasicType(Enum):
    BOOL = "bool"
    CHAR = "char"
    SIGNED_CHAR = "signed-char"
    UNSIGNED_CHAR = "unsigned-char"
    SHORT = "short"
    UNSIGNED_SHORT = "unsigned-short"
    INT = "int"
    UNSIGNED_INT = "unsigned-int"
    LONG = "long"
    UNSIGNED_LONG = "unsigned-long"
    LONG_LONG = "long-long"
    UNSIGNED_LONG_LONG = "unsigned-long-long"
    FLOAT = "float"
    DOUBLE = "double"


@dataclass(frozen=True)
class AstType:
    kind: AstTypeKind
    c_type: str
    bits: int | None = None
    signed: bool | None = None
    name: str | None = None
    target: AstType | None = None
    capacity: int | None = None
    basic_type: BasicType | None = None


@dataclass(frozen=True)
class AstParameter:
    name: str
    type: AstType

    @property
    def type_name(self) -> str:
        return self.type.c_type


@dataclass(frozen=True)
class AstField:
    id: str
    name: str
    type: AstType
    annotations: tuple[Annotation, ...]
    location: SourceLocation

    @property
    def type_name(self) -> str:
        return self.type.c_type


@dataclass(frozen=True)
class AstRecord:
    id: str
    name: str
    fields: tuple[AstField, ...]
    annotations: tuple[Annotation, ...]
    location: SourceLocation
    c_type: str | None = None


@dataclass(frozen=True)
class AstTypedef:
    id: str
    name: str
    type: AstType
    location: SourceLocation

    @property
    def type_name(self) -> str:
        return self.type.c_type


@dataclass(frozen=True)
class AstEnum:
    id: str
    name: str
    integer_type: AstType
    constants: tuple[str, ...]
    location: SourceLocation


@dataclass(frozen=True)
class AstFunction:
    id: str
    name: str
    return_type: AstType
    parameters: tuple[AstParameter, ...]
    annotations: tuple[Annotation, ...]
    location: SourceLocation


@dataclass(frozen=True)
class TranslationUnit:
    input_file: Path
    records: tuple[AstRecord, ...]
    typedefs: tuple[AstTypedef, ...]
    enums: tuple[AstEnum, ...]
    functions: tuple[AstFunction, ...]


_INTEGER_TYPES: dict[str, tuple[BasicType, int, bool]] = {
    "char": (BasicType.CHAR, 8, True),
    "signed char": (BasicType.SIGNED_CHAR, 8, True),
    "unsigned char": (BasicType.UNSIGNED_CHAR, 8, False),
    "short": (BasicType.SHORT, 16, True),
    "short int": (BasicType.SHORT, 16, True),
    "signed short": (BasicType.SHORT, 16, True),
    "signed short int": (BasicType.SHORT, 16, True),
    "unsigned short": (BasicType.UNSIGNED_SHORT, 16, False),
    "unsigned short int": (BasicType.UNSIGNED_SHORT, 16, False),
    "int": (BasicType.INT, 32, True),
    "signed": (BasicType.INT, 32, True),
    "signed int": (BasicType.INT, 32, True),
    "unsigned": (BasicType.UNSIGNED_INT, 32, False),
    "unsigned int": (BasicType.UNSIGNED_INT, 32, False),
    "long": (BasicType.LONG, 64, True),
    "long int": (BasicType.LONG, 64, True),
    "signed long": (BasicType.LONG, 64, True),
    "signed long int": (BasicType.LONG, 64, True),
    "unsigned long": (BasicType.UNSIGNED_LONG, 64, False),
    "unsigned long int": (BasicType.UNSIGNED_LONG, 64, False),
    "long long": (BasicType.LONG_LONG, 64, True),
    "long long int": (BasicType.LONG_LONG, 64, True),
    "signed long long": (BasicType.LONG_LONG, 64, True),
    "signed long long int": (BasicType.LONG_LONG, 64, True),
    "unsigned long long": (BasicType.UNSIGNED_LONG_LONG, 64, False),
    "unsigned long long int": (BasicType.UNSIGNED_LONG_LONG, 64, False),
}


def _normalize_type(text: str) -> str:
    text = re.sub(r"\b(const|volatile|restrict)\b", "", text).strip()
    return re.sub(r"\s+", " ", text)


class CTypeParser:
    """Turns Clang type spellings into a recursive frontend type tree."""

    def __init__(
        self,
        record_names: Iterable[str] = (),
        enum_types: dict[str, tuple[BasicType, int, bool]] | None = None,
        typedefs: dict[str, tuple[str, str | None]] | None = None,
    ):
        self.record_names = set(record_names)
        self.enum_types = enum_types or {}
        self.typedefs = typedefs or {}

    def parse(self, spelling: str, desugared: str | None = None) -> AstType:
        return self._parse(_normalize_type(spelling), desugared, set(), spelling)

    def _parse(
        self,
        text: str,
        desugared: str | None,
        resolving: set[str],
        display: str,
    ) -> AstType:
        c_type = _normalize_type(display)
        array_match = re.fullmatch(r"(.+)\[(\d*)\]", text)
        if array_match:
            element_text, capacity_text = array_match.groups()
            capacity = int(capacity_text) if capacity_text else None
            return AstType(
                AstTypeKind.ARRAY,
                c_type,
                target=self._parse(
                    element_text.strip(), None, resolving, element_text.strip()
                ),
                capacity=capacity,
            )
        if text.endswith("*"):
            target_text = text[:-1].strip()
            return AstType(
                AstTypeKind.POINTER,
                c_type,
                target=self._parse(target_text, None, resolving, target_text),
            )
        if text == "void":
            return AstType(AstTypeKind.VOID, c_type, name="void")
        if text in {"_Bool", "bool"}:
            return AstType(
                AstTypeKind.BOOL,
                c_type,
                bits=8,
                signed=False,
                name=text,
                basic_type=BasicType.BOOL,
            )
        if text in _INTEGER_TYPES:
            basic_type, bits, signed = _INTEGER_TYPES[text]
            return AstType(
                AstTypeKind.INTEGER,
                c_type,
                bits=bits,
                signed=signed,
                name=text,
                basic_type=basic_type,
            )
        if text in {"float", "double"}:
            basic_type = BasicType.FLOAT if text == "float" else BasicType.DOUBLE
            return AstType(
                AstTypeKind.FLOAT,
                c_type,
                bits=32 if text == "float" else 64,
                signed=True,
                name=text,
                basic_type=basic_type,
            )
        if text.startswith("struct "):
            return AstType(
                AstTypeKind.RECORD, c_type, name=text.removeprefix("struct ").strip()
            )
        if text.startswith("enum "):
            name = text.removeprefix("enum ").strip()
            basic_type, bits, signed = self.enum_types.get(
                name, (BasicType.INT, 32, True)
            )
            return AstType(
                AstTypeKind.ENUM,
                c_type,
                bits=bits,
                signed=signed,
                name=name,
                basic_type=basic_type,
            )
        if text in self.record_names:
            return AstType(AstTypeKind.RECORD, c_type, name=text)
        if text in self.enum_types:
            basic_type, bits, signed = self.enum_types[text]
            return AstType(
                AstTypeKind.ENUM,
                c_type,
                bits=bits,
                signed=signed,
                name=text,
                basic_type=basic_type,
            )
        if text in self.typedefs and text not in resolving:
            alias_spelling, alias_desugared = self.typedefs[text]
            resolved = self._parse(
                _normalize_type(alias_spelling),
                alias_desugared,
                resolving | {text},
                alias_spelling,
            )
            return AstType(
                resolved.kind,
                c_type,
                resolved.bits,
                resolved.signed,
                resolved.name,
                resolved.target,
                resolved.capacity,
                resolved.basic_type,
            )
        canonical = _normalize_type(desugared) if desugared else ""
        if canonical and canonical != text:
            resolved = self._parse(canonical, None, resolving, canonical)
            return AstType(
                resolved.kind,
                c_type,
                resolved.bits,
                resolved.signed,
                resolved.name,
                resolved.target,
                resolved.capacity,
                resolved.basic_type,
            )
        return AstType(AstTypeKind.UNKNOWN, c_type, name=text)


def parse_type_spelling(
    spelling: str,
    desugared: str | None = None,
    *,
    record_names: Iterable[str] = (),
    enum_types: dict[str, tuple[BasicType, int, bool]] | None = None,
    typedefs: dict[str, tuple[str, str | None]] | None = None,
) -> AstType:
    """Convenience entry point used by frontend-focused tests and adapters."""

    return CTypeParser(record_names, enum_types, typedefs).parse(spelling, desugared)


def _walk(node: dict[str, Any]) -> Iterable[dict[str, Any]]:
    yield node
    for child in node.get("inner", ()):
        if isinstance(child, dict):
            yield from _walk(child)


def _location(node: dict[str, Any], default_file: Path) -> SourceLocation:
    loc = node.get("loc", {})
    if not loc:
        loc = node.get("range", {}).get("begin", {})
    return SourceLocation(
        str(Path(loc.get("file", default_file))),
        int(loc.get("line", 0)),
        int(loc.get("col", 0)),
    )


@dataclass(frozen=True)
class _SourceComment:
    start_offset: int
    end_offset: int
    start_line: int
    end_line: int
    text: str
    location: SourceLocation
    trailing: bool


def _line_number(source: bytes, offset: int) -> int:
    return source.count(b"\n", 0, offset) + 1


def _line_end(source: bytes, offset: int) -> int:
    end = source.find(b"\n", offset)
    return len(source) if end < 0 else end


def _strip_document_comment(text: str) -> str:
    lines = text.splitlines()
    result: list[str] = []
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith(("///", "//!", "/**", "/*!")):
            stripped = stripped[3:]
        elif stripped.startswith("/*"):
            stripped = stripped[2:]
        stripped = stripped.removesuffix("*/")
        stripped = stripped.lstrip()
        if stripped.startswith("*"):
            stripped = stripped[1:].lstrip()
        result.append(stripped)
    return "\n".join(result)


def _make_source_comment(
    source: bytes, default_file: Path, start: int, end: int, trailing: bool
) -> _SourceComment:
    start_line = _line_number(source, start)
    end_line = _line_number(source, max(start, end - 1))
    line_start = source.rfind(b"\n", 0, start) + 1
    return _SourceComment(
        start,
        end,
        start_line,
        end_line,
        _strip_document_comment(source[start:end].decode("utf-8")),
        SourceLocation(str(default_file), start_line, start - line_start + 1),
        trailing,
    )


def _scan_source_comments(
    source: bytes, default_file: Path
) -> tuple[_SourceComment, ...]:
    comments: list[_SourceComment] = []
    index = 0
    while index < len(source):
        byte = source[index]
        if byte in (ord('"'), ord("'")):
            quote = byte
            index += 1
            while index < len(source):
                if source[index] == ord("\\"):
                    index += 2
                elif source[index] == quote:
                    index += 1
                    break
                else:
                    index += 1
            continue
        if source[index : index + 2] == b"//":
            end = _line_end(source, index)
            if source[index : index + 3] in (b"///", b"//!"):
                line_start = source.rfind(b"\n", 0, index) + 1
                trailing = bool(source[line_start:index].strip())
                comments.append(
                    _make_source_comment(source, default_file, index, end, trailing)
                )
            index = end
            continue
        if source[index : index + 2] == b"/*":
            close = source.find(b"*/", index + 2)
            end = len(source) if close < 0 else close + 2
            if source[index : index + 3] in (b"/**", b"/*!"):
                line_start = source.rfind(b"\n", 0, index) + 1
                trailing = bool(source[line_start:index].strip())
                comments.append(
                    _make_source_comment(source, default_file, index, end, trailing)
                )
            index = end
            continue
        index += 1

    grouped: list[_SourceComment] = []
    for comment in comments:
        if (
            grouped
            and not grouped[-1].trailing
            and not comment.trailing
            and grouped[-1].end_line + 1 == comment.start_line
        ):
            previous = grouped.pop()
            grouped.append(
                _make_source_comment(
                    source,
                    default_file,
                    previous.start_offset,
                    comment.end_offset,
                    False,
                )
            )
        else:
            grouped.append(comment)
    return tuple(grouped)


def _node_line_range(node: dict[str, Any], source: bytes) -> tuple[int, int, int]:
    source_range = node.get("range", {})
    begin = source_range.get("begin", {})
    end = source_range.get("end", {})
    begin_offset = int(begin.get("offset", node.get("loc", {}).get("offset", 0)))
    end_offset = int(end.get("offset", begin_offset)) + int(end.get("tokLen", 0))
    begin_line = int(begin.get("line") or _line_number(source, begin_offset))
    end_line = int(end.get("line") or _line_number(source, end_offset))
    return begin_line, end_line, end_offset


def _belongs_to_default_source(
    node: dict[str, Any], default_file: Path, source: bytes
) -> bool:
    loc = node.get("loc", {})
    if loc.get("file") is not None:
        return Path(loc["file"]).resolve() == default_file.resolve()
    offset = loc.get("offset")
    token_length = int(loc.get("tokLen", 0))
    node_name = node.get("name", "")
    return (
        offset is not None
        and bool(node_name)
        and source[int(offset) : int(offset) + token_length].decode("utf-8")
        == node_name
    )


def _node_annotations(
    node: dict[str, Any],
    default_file: Path,
    source: bytes,
    comments: tuple[_SourceComment, ...],
) -> tuple[Annotation, ...]:
    if not _belongs_to_default_source(node, default_file, source):
        return ()
    begin_line, end_line, end_offset = _node_line_range(node, source)
    leading = [
        comment
        for comment in comments
        if not comment.trailing and comment.end_line + 1 == begin_line
    ]
    if leading:
        comment = leading[-1]
        annotations = parse_annotations(comment.text, comment.location)
        if annotations:
            return annotations
    trailing = [
        comment
        for comment in comments
        if comment.trailing
        and comment.start_line == end_line
        and comment.start_offset >= end_offset
    ]
    if trailing:
        comment = trailing[0]
        return parse_annotations(comment.text, comment.location)
    return ()


class ClangFrontend:
    def __init__(self, clang: str = "clang"):
        self.clang = clang

    def parse(
        self,
        input_file: Path,
        clang_args: Iterable[str] = (),
        working_directory: Path | None = None,
    ) -> TranslationUnit:
        input_file = input_file.resolve()
        source = input_file.read_bytes()
        try:
            source.decode("utf-8")
        except UnicodeDecodeError as error:
            raise FrontendError(f"input header is not valid UTF-8: {error}") from error
        command = [
            self.clang,
            "-x",
            "c",
            "-std=c11",
            "-fsyntax-only",
            "-Xclang",
            "-ast-dump=json",
            *clang_args,
            str(input_file),
        ]
        process = subprocess.run(
            command,
            cwd=working_directory,
            text=True,
            capture_output=True,
            check=False,
        )
        if process.returncode != 0:
            raise FrontendError(
                process.stderr.strip() or f"clang exited with {process.returncode}"
            )
        try:
            root = json.loads(process.stdout)
        except json.JSONDecodeError as error:
            raise FrontendError(f"clang produced invalid JSON AST: {error}") from error
        return self.from_json(root, input_file, source)

    def from_json(
        self, root: dict[str, Any], input_file: Path, source: bytes | str
    ) -> TranslationUnit:
        if isinstance(source, str):
            source = source.encode("utf-8")
        comments = _scan_source_comments(source, input_file)
        records: list[AstRecord] = []
        typedefs: list[AstTypedef] = []
        enums: list[AstEnum] = []
        functions: list[AstFunction] = []
        seen: set[str] = set()

        owned_records: dict[str, tuple[str, dict[str, Any]]] = {}
        for node in _walk(root):
            if node.get("kind") != "TypedefDecl" or not node.get("name"):
                continue
            for type_node in _walk(node):
                owned = type_node.get("ownedTagDecl")
                if isinstance(owned, dict) and owned.get("id"):
                    owned_records[owned["id"]] = (node["name"], node)
                    break

        record_names: set[str] = set()
        typedef_specs: dict[str, tuple[str, str | None]] = {}
        enum_types: dict[str, tuple[BasicType, int, bool]] = {}
        for node in _walk(root):
            kind = node.get("kind")
            if kind == "RecordDecl" and node.get("completeDefinition"):
                name = node.get("name")
                typedef_info = owned_records.get(node.get("id", ""))
                if name or typedef_info:
                    record_names.add(name or typedef_info[0])
            elif kind == "TypedefDecl" and node.get("name"):
                type_info = node.get("type", {})
                typedef_specs[node["name"]] = (
                    type_info.get("qualType", ""),
                    type_info.get("desugaredQualType"),
                )
            elif kind == "EnumDecl" and node.get("name"):
                underlying = _normalize_type(
                    node.get("fixedUnderlyingType", {}).get("qualType", "int")
                )
                enum_types[node["name"]] = _INTEGER_TYPES.get(
                    underlying, (BasicType.INT, 32, True)
                )
        type_parser = CTypeParser(record_names, enum_types, typedef_specs)

        for node in _walk(root):
            node_id = node.get("id", "")
            kind = node.get("kind")
            if not node_id or node_id in seen:
                continue
            if kind == "RecordDecl" and node.get("completeDefinition"):
                tag_name = node.get("name")
                typedef_info = owned_records.get(node_id)
                typedef_name = typedef_info[0] if typedef_info else None
                record_name = tag_name or typedef_name
                if not record_name:
                    continue
                seen.add(node_id)
                fields: list[AstField] = []
                for child in node.get("inner", ()):
                    if child.get("kind") != "FieldDecl" or not child.get("name"):
                        continue
                    type_info = child.get("type", {})
                    fields.append(
                        AstField(
                            child.get("id", ""),
                            child["name"],
                            type_parser.parse(
                                type_info.get("qualType", ""),
                                type_info.get("desugaredQualType"),
                            ),
                            _node_annotations(child, input_file, source, comments),
                            _location(child, input_file),
                        )
                    )
                annotations = _node_annotations(node, input_file, source, comments)
                if not annotations and typedef_info is not None:
                    annotations = _node_annotations(
                        typedef_info[1], input_file, source, comments
                    )
                records.append(
                    AstRecord(
                        node_id,
                        record_name,
                        tuple(fields),
                        annotations,
                        _location(node, input_file),
                        f"struct {tag_name}" if tag_name else typedef_name,
                    )
                )
            elif kind == "TypedefDecl" and node.get("name"):
                seen.add(node_id)
                type_info = node.get("type", {})
                typedefs.append(
                    AstTypedef(
                        node_id,
                        node["name"],
                        type_parser.parse(
                            type_info.get("qualType", ""),
                            type_info.get("desugaredQualType"),
                        ),
                        _location(node, input_file),
                    )
                )
            elif kind == "EnumDecl" and node.get("name"):
                seen.add(node_id)
                enums.append(
                    AstEnum(
                        node_id,
                        node["name"],
                        type_parser.parse(
                            node.get("fixedUnderlyingType", {}).get("qualType", "int")
                        ),
                        tuple(
                            child["name"]
                            for child in node.get("inner", ())
                            if child.get("kind") == "EnumConstantDecl"
                            and child.get("name")
                        ),
                        _location(node, input_file),
                    )
                )
            elif kind == "FunctionDecl" and node.get("name"):
                if not _belongs_to_default_source(node, input_file, source):
                    continue
                annotations = _node_annotations(node, input_file, source, comments)
                if not annotations:
                    continue
                seen.add(node_id)
                parameters = []
                for child in node.get("inner", ()):
                    if child.get("kind") == "ParmVarDecl":
                        type_info = child.get("type", {})
                        parameters.append(
                            AstParameter(
                                child.get("name", ""),
                                type_parser.parse(
                                    type_info.get("qualType", ""),
                                    type_info.get("desugaredQualType"),
                                ),
                            )
                        )
                function_type = node.get("type", {})
                return_spelling = (
                    function_type.get("qualType", "").split("(", 1)[0].strip()
                )
                return_desugared_text = function_type.get("desugaredQualType")
                return_desugared = (
                    return_desugared_text.split("(", 1)[0].strip()
                    if return_desugared_text
                    else None
                )
                functions.append(
                    AstFunction(
                        node_id,
                        node["name"],
                        type_parser.parse(return_spelling, return_desugared),
                        tuple(parameters),
                        annotations,
                        _location(node, input_file),
                    )
                )
        return TranslationUnit(
            input_file, tuple(records), tuple(typedefs), tuple(enums), tuple(functions)
        )
