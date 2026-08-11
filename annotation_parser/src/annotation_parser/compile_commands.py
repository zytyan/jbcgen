from __future__ import annotations

import json
import os
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .diagnostics import FrontendError


@dataclass(frozen=True)
class CompileCommand:
    directory: Path
    source: Path
    arguments: tuple[str, ...]


_SEPARATE_OUTPUT_OPTIONS = {"-o", "-MF", "-MT", "-MQ", "-MJ", "--output"}
_JOINED_OUTPUT_OPTIONS = ("-o", "-MF", "-MT", "-MQ", "-MJ")
_ACTION_OPTIONS = {"-c", "-S", "-E", "-M", "-MM", "-MD", "-MMD", "-MP", "-MG"}
_COMPILER_WRAPPERS = {"ccache", "sccache", "distcc"}


def _entry_arguments(entry: dict[str, Any], index: int) -> list[str]:
    arguments = entry.get("arguments")
    if isinstance(arguments, list) and all(isinstance(item, str) for item in arguments):
        return list(arguments)
    command = entry.get("command")
    if isinstance(command, str):
        try:
            return shlex.split(command, posix=os.name != "nt")
        except ValueError as error:
            raise FrontendError(
                f"invalid command in compile_commands.json entry {index}: {error}"
            ) from error
    raise FrontendError(
        f"compile_commands.json entry {index} must contain 'arguments' or 'command'"
    )


def _entry_path(value: object, directory: Path, name: str, index: int) -> Path:
    if not isinstance(value, str) or not value:
        raise FrontendError(f"compile_commands.json entry {index} has invalid '{name}'")
    path = Path(value)
    if not path.is_absolute():
        path = directory / path
    return path.resolve()


def _strip_driver_arguments(
    arguments: list[str], source: Path, directory: Path
) -> tuple[str, ...]:
    if not arguments:
        raise FrontendError("compile command has no compiler executable")
    cursor = 1
    if Path(arguments[0]).name in _COMPILER_WRAPPERS and len(arguments) > 1:
        cursor += 1

    result: list[str] = []
    while cursor < len(arguments):
        argument = arguments[cursor]
        cursor += 1
        if argument in _SEPARATE_OUTPUT_OPTIONS:
            if cursor < len(arguments):
                cursor += 1
            continue
        if argument in _ACTION_OPTIONS or argument == "--":
            continue
        if any(
            argument.startswith(prefix) and argument != prefix
            for prefix in _JOINED_OUTPUT_OPTIONS
        ):
            continue
        if not argument.startswith("-"):
            candidate = Path(argument)
            if not candidate.is_absolute():
                candidate = directory / candidate
            if candidate.resolve() == source:
                continue
        result.append(argument)
    return tuple(result)


def _path_distance(left: Path, right: Path) -> tuple[int, int]:
    left_parts = left.parts
    right_parts = right.parts
    common = 0
    for left_part, right_part in zip(left_parts, right_parts, strict=False):
        if left_part != right_part:
            break
        common += 1
    return common, -((len(left_parts) - common) + (len(right_parts) - common))


def _selection_key(
    command: CompileCommand, input_file: Path
) -> tuple[int, int, int, str]:
    common, distance = _path_distance(command.source.parent, input_file.parent)
    return (
        int(command.source.stem == input_file.stem),
        common,
        distance,
        str(command.source),
    )


def load_compile_command(database: Path, input_file: Path) -> CompileCommand:
    database = database.resolve()
    if database.is_dir():
        database = database / "compile_commands.json"
    try:
        contents = json.loads(database.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise FrontendError(f"compilation database not found: {database}") from error
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise FrontendError(
            f"cannot read compilation database {database}: {error}"
        ) from error
    if not isinstance(contents, list) or not contents:
        raise FrontendError(f"compilation database is empty or invalid: {database}")

    commands: list[CompileCommand] = []
    for index, value in enumerate(contents):
        if not isinstance(value, dict):
            raise FrontendError(f"compile_commands.json entry {index} is not an object")
        directory = _entry_path(
            value.get("directory"), database.parent, "directory", index
        )
        source = _entry_path(value.get("file"), directory, "file", index)
        arguments = _strip_driver_arguments(
            _entry_arguments(value, index), source, directory
        )
        commands.append(CompileCommand(directory, source, arguments))

    input_file = input_file.resolve()
    exact = [command for command in commands if command.source == input_file]
    if exact:
        return exact[0]
    return max(commands, key=lambda command: _selection_key(command, input_file))
