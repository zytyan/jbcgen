from __future__ import annotations

from dataclasses import dataclass

from .lexer import Token, TokenKind, tokenize


@dataclass(frozen=True)
class Expression:
    pass


@dataclass(frozen=True)
class StringExpression(Expression):
    value: str


@dataclass(frozen=True)
class KeyValueExpression(Expression):
    key: StringExpression
    value: Expression


@dataclass(frozen=True)
class CallExpression(Expression):
    function: StringExpression
    arguments: tuple[Expression, ...]


class Parser:
    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.index = 0

    def peek(self) -> Token:
        return self.tokens[min(self.index, len(self.tokens) - 1)]

    def next(self) -> Token:
        token = self.peek()
        self.index += 1
        return token

    def expect_kind(self, *kinds: TokenKind) -> Token:
        token = self.peek()
        if token.kind not in kinds:
            raise SyntaxError(
                f"expected {kinds} at offset {token.offset}, got {token.kind.value}"
            )
        return self.next()

    def expect_punctuation(self, value: str) -> Token:
        token = self.peek()
        if token.kind is not TokenKind.PUNCTUATION or token.value != value:
            raise SyntaxError(
                f"expected {value!r} at offset {token.offset}, got {token.value!r}"
            )
        return self.next()

    def parse_identifier(self) -> StringExpression:
        return StringExpression(self.expect_kind(TokenKind.IDENT).value)

    def parse_expression(self) -> Expression:
        token = self.peek()
        if token.kind is TokenKind.STRING:
            return StringExpression(self.next().value)
        if token.kind is not TokenKind.IDENT:
            raise SyntaxError(f"expected expression at offset {token.offset}")
        value = self.parse_identifier()
        if self.peek().value == "=":
            self.next()
            return KeyValueExpression(value, self.parse_expression())
        if self.peek().value == "(":
            return self.parse_call(value)
        return value

    def parse_call(self, function: StringExpression | None = None) -> CallExpression:
        function = function or self.parse_identifier()
        self.expect_punctuation("(")
        arguments: list[Expression] = []
        if self.peek().value != ")":
            arguments.append(self.parse_expression())
            while self.peek().value == ",":
                self.next()
                if self.peek().value == ")":
                    break
                arguments.append(self.parse_expression())
        self.expect_punctuation(")")
        return CallExpression(function, tuple(arguments))

    def parse_annotation(self) -> CallExpression:
        function = self.parse_identifier()
        result = (
            self.parse_call(function)
            if self.peek().value == "("
            else CallExpression(function, ())
        )
        self.expect_kind(TokenKind.EOF)
        return result


def parse_annotation(text: str) -> CallExpression:
    return Parser(tokenize(text)).parse_annotation()
