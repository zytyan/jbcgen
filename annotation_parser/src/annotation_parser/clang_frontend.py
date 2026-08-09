from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .annotations import Annotation, parse_annotations
from .diagnostics import FrontendError, SourceLocation


@dataclass(frozen=True)
class AstParameter:
    name: str
    type_name: str
    desugared_type: str | None


@dataclass(frozen=True)
class AstField:
    id: str
    name: str
    type_name: str
    desugared_type: str | None
    annotations: tuple[Annotation, ...]
    location: SourceLocation


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
    type_name: str
    desugared_type: str | None
    location: SourceLocation


@dataclass(frozen=True)
class AstEnum:
    id: str
    name: str
    integer_type: str | None
    constants: tuple[str, ...]
    location: SourceLocation


@dataclass(frozen=True)
class AstFunction:
    id: str
    name: str
    type_name: str
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


def _comment_text(node: dict[str, Any]) -> str:
    pieces: list[str] = []
    for item in _walk(node):
        if item.get("kind") == "InlineCommandComment":
            pieces.append("@" + item.get("name", ""))
        elif item.get("kind") == "TextComment":
            pieces.append(item.get("text", ""))
    return "\n".join(pieces)


def _is_trailing_source_comment(node: dict[str, Any], source: str) -> bool:
    begin = node.get("range", {}).get("begin", {})
    offset = begin.get("offset")
    if offset is None:
        return False
    offset = int(offset)
    line_start = source.rfind("\n", 0, offset) + 1
    prefix = source[line_start:offset]
    markers = [position for marker in ("///", "/**") if (position := prefix.rfind(marker)) >= 0]
    if not markers:
        return False
    return bool(prefix[: max(markers)].strip())


def _leading_source_comment(node: dict[str, Any], source: str) -> str:
    begin = node.get("range", {}).get("begin", {})
    offset = begin.get("offset")
    if offset is None:
        return ""
    line_start = source.rfind("\n", 0, int(offset)) + 1
    prefix = source[:line_start].splitlines()
    if not prefix:
        return ""
    index = len(prefix) - 1
    stripped = prefix[index].strip()
    if stripped.startswith("///"):
        comments: list[str] = []
        while index >= 0 and prefix[index].strip().startswith("///"):
            comments.append(prefix[index].strip()[3:])
            index -= 1
        return "\n".join(reversed(comments))
    if stripped.endswith("*/"):
        comments = []
        while index >= 0:
            line = prefix[index].strip()
            comments.append(line)
            if "/**" in line:
                before, _, after = line.partition("/**")
                if before.strip():
                    return ""
                comments[-1] = after
                break
            index -= 1
        else:
            return ""
        text = "\n".join(reversed(comments))
        text = text.rsplit("*/", 1)[0]
        return "\n".join(line.lstrip("* ") for line in text.splitlines())
    return ""


def _belongs_to_default_source(node: dict[str, Any], default_file: Path, source: str) -> bool:
    loc = node.get("loc", {})
    if loc.get("file") is not None:
        return Path(loc["file"]).resolve() == default_file.resolve()
    offset = loc.get("offset")
    token_length = int(loc.get("tokLen", 0))
    node_name = node.get("name", "")
    return (
        offset is not None
        and bool(node_name)
        and source[int(offset) : int(offset) + token_length] == node_name
    )


def _node_annotations(node: dict[str, Any], default_file: Path, source: str) -> tuple[Annotation, ...]:
    location = _location(node, default_file)
    belongs_to_default = _belongs_to_default_source(node, default_file, source)
    if belongs_to_default:
        leading = _leading_source_comment(node, source)
        if leading:
            parsed = parse_annotations(leading, location)
            if parsed:
                return parsed
    annotations: list[Annotation] = []
    for child in node.get("inner", ()):
        if child.get("kind") == "FullComment" and not _is_trailing_source_comment(child, source):
            annotations.extend(parse_annotations(_comment_text(child), location))

    # Clang does not attach a documentation comment placed after a field.
    if not annotations and node.get("kind") == "FieldDecl" and belongs_to_default:
        end = node.get("range", {}).get("end", {})
        offset = end.get("offset")
        token_length = end.get("tokLen", 0)
        if offset is not None:
            line_end = source.find("\n", int(offset) + int(token_length))
            if line_end < 0:
                line_end = len(source)
            tail = source[int(offset) + int(token_length) : line_end]
            marker = tail.find("///")
            if marker >= 0:
                annotations.extend(parse_annotations(tail[marker + 3 :], location))
    return tuple(annotations)


class ClangFrontend:
    def __init__(self, clang: str = "clang"):
        self.clang = clang

    def parse(self, input_file: Path, clang_args: Iterable[str] = ()) -> TranslationUnit:
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
        process = subprocess.run(command, text=True, capture_output=True, check=False)
        if process.returncode != 0:
            raise FrontendError(process.stderr.strip() or f"clang exited with {process.returncode}")
        try:
            root = json.loads(process.stdout)
        except json.JSONDecodeError as error:
            raise FrontendError(f"clang produced invalid JSON AST: {error}") from error
        return self.from_json(root, input_file, source)

    def from_json(self, root: dict[str, Any], input_file: Path, source: str) -> TranslationUnit:
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
                            type_info.get("qualType", ""),
                            type_info.get("desugaredQualType"),
                            _node_annotations(child, input_file, source),
                            _location(child, input_file),
                        )
                    )
                annotations = _node_annotations(node, input_file, source)
                if not annotations and typedef_info is not None:
                    annotations = _node_annotations(typedef_info[1], input_file, source)
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
                        type_info.get("qualType", ""),
                        type_info.get("desugaredQualType"),
                        _location(node, input_file),
                    )
                )
            elif kind == "EnumDecl" and node.get("name"):
                seen.add(node_id)
                enums.append(
                    AstEnum(
                        node_id,
                        node["name"],
                        node.get("fixedUnderlyingType", {}).get("qualType"),
                        tuple(
                            child["name"]
                            for child in node.get("inner", ())
                            if child.get("kind") == "EnumConstantDecl" and child.get("name")
                        ),
                        _location(node, input_file),
                    )
                )
            elif kind == "FunctionDecl" and node.get("name"):
                if not _belongs_to_default_source(node, input_file, source):
                    continue
                annotations = _node_annotations(node, input_file, source)
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
                                type_info.get("qualType", ""),
                                type_info.get("desugaredQualType"),
                            )
                        )
                functions.append(
                    AstFunction(
                        node_id,
                        node["name"],
                        node.get("type", {}).get("qualType", ""),
                        tuple(parameters),
                        annotations,
                        _location(node, input_file),
                    )
                )
        return TranslationUnit(input_file, tuple(records), tuple(typedefs), tuple(enums), tuple(functions))
