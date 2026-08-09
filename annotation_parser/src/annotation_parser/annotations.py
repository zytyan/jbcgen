from __future__ import annotations

from dataclasses import dataclass

from .diagnostics import AnnotationError, SourceLocation
from .parser import CallExpression, KeyValueExpression, StringExpression, parse_annotation


@dataclass(frozen=True)
class AnnotationArgument:
    name: str
    value: str | None


@dataclass(frozen=True)
class Annotation:
    name: str
    arguments: tuple[AnnotationArgument, ...]
    location: SourceLocation | None = None

    def values(self, name: str) -> tuple[str | None, ...]:
        return tuple(argument.value for argument in self.arguments if argument.name == name)


_KNOWN_COMMANDS = {"json", "jsonStruct", "jsonDecode", "jsonCleanup"}
_JSON_ARGUMENTS = {
    "key",
    "altkey",
    "required",
    "min",
    "max",
    "minlen",
    "maxlen",
    "type",
    "len",
    "flatten",
    "omitempty",
}
_FLAGS = {"required", "flatten", "omitempty"}
_REPEATABLE = {"altkey"}


def _calls_in_text(text: str) -> list[str]:
    calls: list[str] = []
    index = 0
    while index < len(text):
        marker = text.find("@", index)
        if marker < 0:
            break
        end = marker + 1
        while end < len(text) and (text[end].isalnum() or text[end] == "_"):
            end += 1
        if end == marker + 1:
            index = end
            continue
        cursor = end
        while cursor < len(text) and text[cursor].isspace():
            cursor += 1
        if cursor < len(text) and text[cursor] == "(":
            depth = 0
            quote: str | None = None
            escaped = False
            while cursor < len(text):
                char = text[cursor]
                if quote is not None:
                    if escaped:
                        escaped = False
                    elif char == "\\":
                        escaped = True
                    elif char == quote:
                        quote = None
                elif char in "'\"`":
                    quote = char
                elif char == "(":
                    depth += 1
                elif char == ")":
                    depth -= 1
                    if depth == 0:
                        cursor += 1
                        break
                cursor += 1
            if depth != 0:
                raise SyntaxError(f"unterminated annotation starting at offset {marker}")
            end = cursor
        calls.append(text[marker + 1 : end])
        index = end
    return calls


def parse_annotations(text: str, location: SourceLocation | None = None) -> tuple[Annotation, ...]:
    result: list[Annotation] = []
    for text_call in _calls_in_text(text):
        try:
            call = parse_annotation(text_call)
        except SyntaxError as error:
            raise AnnotationError(str(error), location) from error
        result.append(_validate(call, location))
    return tuple(result)


def _validate(call: CallExpression, location: SourceLocation | None) -> Annotation:
    name = call.function.value
    if name not in _KNOWN_COMMANDS:
        raise AnnotationError(f"unknown annotation @{name}", location)
    if name != "json":
        if call.arguments:
            raise AnnotationError(f"@{name} does not accept arguments", location)
        return Annotation(name, (), location)

    arguments: list[AnnotationArgument] = []
    seen: set[str] = set()
    for expression in call.arguments:
        if isinstance(expression, StringExpression):
            argument = AnnotationArgument(expression.value, None)
        elif isinstance(expression, KeyValueExpression) and isinstance(expression.value, StringExpression):
            argument = AnnotationArgument(expression.key.value, expression.value.value)
        else:
            raise AnnotationError("@json arguments must be flags or scalar key/value pairs", location)
        if argument.name not in _JSON_ARGUMENTS:
            raise AnnotationError(f"unknown @json argument {argument.name!r}", location)
        if argument.name in _FLAGS and argument.value is not None:
            raise AnnotationError(f"@json argument {argument.name!r} is a flag", location)
        if argument.name not in _FLAGS and argument.value is None:
            raise AnnotationError(f"@json argument {argument.name!r} requires a value", location)
        if argument.name in seen and argument.name not in _REPEATABLE:
            raise AnnotationError(f"duplicate @json argument {argument.name!r}", location)
        seen.add(argument.name)
        arguments.append(argument)
    return Annotation(name, tuple(arguments), location)
