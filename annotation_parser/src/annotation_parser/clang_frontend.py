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


def _line_number(source: str, offset: int) -> int:
    return source.encode("utf-8").count(b"\n", 0, offset) + 1


def _line_end(source: str, offset: int) -> int:
    source_bytes = source.encode("utf-8")
    end = source_bytes.find(b"\n", offset)
    return len(source_bytes) if end < 0 else end


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


def _source_comment(
    node: dict[str, Any], default_file: Path, source: str
) -> _SourceComment | None:
    source_range = node.get("range", {})
    begin = source_range.get("begin", {})
    end = source_range.get("end", {})
    if begin.get("includedFrom") or end.get("includedFrom"):
        return None
    begin_offset = begin.get("offset")
    end_offset = end.get("offset")
    if begin_offset is None or end_offset is None:
        return None
    source_bytes = source.encode("utf-8")
    content_begin = int(begin_offset)
    content_end = int(end_offset) + max(int(end.get("tokLen", 0)), 1)
    if not (0 <= content_begin <= content_end <= len(source_bytes)):
        return None

    begin_line_start = source_bytes.rfind(b"\n", 0, content_begin) + 1
    prefix = source_bytes[begin_line_start:content_begin]
    trailing = False
    block_start = source_bytes.rfind(b"/**", 0, content_begin + 1)
    block_close_before = source_bytes.rfind(b"*/", 0, content_begin + 1)
    block_start_inside = source_bytes.rfind(b"/**", content_begin, content_end + 1)
    if block_start_inside >= 0:
        block_start = block_start_inside
    if (
        block_start_inside >= 0
        or block_start >= begin_line_start
        or block_start > block_close_before
    ):
        start_offset = block_start
        close = source_bytes.find(b"*/", content_end)
        if close < 0:
            return None
        end_offset_exclusive = close + 2
    elif b"///" in prefix or b"//!" in prefix:
        marker_offsets = [
            begin_line_start + position
            for marker in (b"///", b"//!")
            if (position := prefix.rfind(marker)) >= 0
        ]
        start_offset = max(marker_offsets)
        trailing = bool(source_bytes[begin_line_start:start_offset].strip())
        end_offset_exclusive = (
            _line_end(source, content_begin)
            if trailing
            else _line_end(source, content_end)
        )
    else:
        return None

    start_line = _line_number(source, start_offset)
    end_line = _line_number(source, max(start_offset, end_offset_exclusive - 1))
    column = start_offset - (source_bytes.rfind(b"\n", 0, start_offset) + 1) + 1
    return _SourceComment(
        start_offset,
        end_offset_exclusive,
        start_line,
        end_line,
        _strip_document_comment(
            source_bytes[start_offset:end_offset_exclusive].decode("utf-8")
        ),
        SourceLocation(str(default_file), start_line, column),
        trailing,
    )


def _source_comments(
    root: dict[str, Any], default_file: Path, source: str
) -> tuple[_SourceComment, ...]:
    by_range: dict[tuple[int, int], _SourceComment] = {}
    for node in _walk(root):
        if node.get("kind") != "FullComment":
            continue
        comment = _source_comment(node, default_file, source)
        if comment is not None:
            by_range[(comment.start_offset, comment.end_offset)] = comment
    source_bytes = source.encode("utf-8")
    lines = source_bytes.splitlines(keepends=True)
    line_offsets: list[int] = []
    offset = 0
    for line in lines:
        line_offsets.append(offset)
        offset += len(line)
    index = 0
    while index < len(lines):
        line = lines[index]
        marker_indexes = [
            position
            for marker in (b"///", b"//!")
            if (position := line.find(marker)) >= 0
        ]
        if not marker_indexes:
            index += 1
            continue
        marker_index = min(marker_indexes)
        trailing = bool(line[:marker_index].strip())
        start_index = index
        end_index = index
        if not trailing:
            while end_index + 1 < len(lines):
                next_line = lines[end_index + 1].lstrip()
                if not next_line.startswith((b"///", b"//!")):
                    break
                end_index += 1
        start_offset = line_offsets[start_index] + marker_index
        end_offset = line_offsets[end_index] + len(lines[end_index].rstrip(b"\r\n"))
        by_range[(start_offset, end_offset)] = _SourceComment(
            start_offset,
            end_offset,
            start_index + 1,
            end_index + 1,
            _strip_document_comment(
                source_bytes[start_offset:end_offset].decode("utf-8")
            ),
            SourceLocation(str(default_file), start_index + 1, marker_index + 1),
            trailing,
        )
        index = end_index + 1
    return tuple(sorted(by_range.values(), key=lambda item: item.start_offset))


def _node_line_range(node: dict[str, Any], source: str) -> tuple[int, int, int]:
    source_range = node.get("range", {})
    begin = source_range.get("begin", {})
    end = source_range.get("end", {})
    begin_offset = int(begin.get("offset", node.get("loc", {}).get("offset", 0)))
    end_offset = int(end.get("offset", begin_offset)) + int(end.get("tokLen", 0))
    begin_line = int(begin.get("line") or _line_number(source, begin_offset))
    end_line = int(end.get("line") or _line_number(source, end_offset))
    return begin_line, end_line, end_offset


def _belongs_to_default_source(
    node: dict[str, Any], default_file: Path, source: str
) -> bool:
    loc = node.get("loc", {})
    if loc.get("file") is not None:
        return Path(loc["file"]).resolve() == default_file.resolve()
    offset = loc.get("offset")
    token_length = int(loc.get("tokLen", 0))
    node_name = node.get("name", "")
    source_bytes = source.encode("utf-8")
    return (
        offset is not None
        and bool(node_name)
        and source_bytes[int(offset) : int(offset) + token_length].decode("utf-8")
        == node_name
    )


def _node_annotations(
    node: dict[str, Any],
    default_file: Path,
    source: str,
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
        source = input_file.read_text(encoding="utf-8")
        command = [
            self.clang,
            "-x",
            "c",
            "-std=c11",
            "-fsyntax-only",
            "-fparse-all-comments",
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
        self, root: dict[str, Any], input_file: Path, source: str
    ) -> TranslationUnit:
        comments = _source_comments(root, input_file, source)
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
