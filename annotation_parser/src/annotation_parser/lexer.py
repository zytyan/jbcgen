from __future__ import annotations

import codecs
import enum
import re
from dataclasses import dataclass


class TokenKind(enum.Enum):
    STRING = "string"
    IDENT = "identifier"
    PUNCTUATION = "punctuation"
    EOF = "eof"


@dataclass(frozen=True)
class Token:
    kind: TokenKind
    value: str
    offset: int


_PUNCTUATION = "(){}[]=,@$"


def _normal_string(text: str, start: int) -> tuple[str, int]:
    quote = text[start]
    index = start + 1
    result: list[str] = []
    while index < len(text):
        char = text[index]
        if char == quote:
            return "".join(result), index + 1
        if char != "\\":
            result.append(char)
            index += 1
            continue
        if index + 1 >= len(text):
            break
        escaped = text[index : index + 2]
        try:
            result.append(codecs.decode(escaped, "unicode_escape"))
        except UnicodeDecodeError as error:
            raise SyntaxError(f"invalid escape at offset {index}: {escaped}") from error
        index += 2
    raise SyntaxError(f"unterminated string at offset {start}")


def _raw_string(text: str, start: int, match: re.Match[str]) -> tuple[str, int]:
    opening = match.group(0)
    closing = opening[1:][::-1]
    content_start = start + len(opening)
    relative_end = text.find(closing, content_start)
    if relative_end < 0:
        raise SyntaxError(f"unterminated raw string at offset {start}")
    return text[content_start:relative_end], relative_end + len(closing)


def tokenize(text: str) -> list[Token]:
    result: list[Token] = []
    index = 0
    escaped_punctuation = re.escape(_PUNCTUATION)
    while index < len(text):
        char = text[index]
        if char.isspace():
            index += 1
        elif char in _PUNCTUATION:
            result.append(Token(TokenKind.PUNCTUATION, char, index))
            index += 1
        elif re.match(r"[rR](?:\#*)['\"`]", text[index:]):
            match = re.match(r"[rR](?:\#*)['\"`]", text[index:])
            assert match is not None
            value, end = _raw_string(text, index, match)
            result.append(Token(TokenKind.STRING, value, index))
            index = end
        elif char in "'\"`":
            value, end = _normal_string(text, index)
            result.append(Token(TokenKind.STRING, value, index))
            index = end
        else:
            match = re.match(rf"[^\s='\`\"{escaped_punctuation}]+", text[index:])
            if match is None:
                raise SyntaxError(f"unexpected token at offset {index}: {text[index:]}")
            value = match.group(0)
            result.append(Token(TokenKind.IDENT, value, index))
            index += len(value)
    result.append(Token(TokenKind.EOF, "", len(text)))
    return result
