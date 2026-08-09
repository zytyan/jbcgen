import sys
from dataclasses import dataclass
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from annoation_parser.lexer import Token, TokenKind, tokenize


@dataclass
class Expr:
    pass


@dataclass
class StrExpr(Expr):
    val: str


@dataclass
class KvExpr(Expr):
    key: StrExpr
    value: Expr | None


@dataclass
class FnExpr(Expr):
    fn: StrExpr
    args: list[Expr]


class Parser:
    """
    Stmt := FnExpr;
    FnExpr := NakedStr '(' ArgsList ? ')' ;
    ArgsList := Expr  ( ',' Expr)+  ','? ;
    # 这里似乎会引入递归，不过倒也没那么重要就是了。
    KvExpr := NakedStr '=' Expr ;
    Expr := KvExpr | FnExpr | NakedStr;
    """

    def __init__(self, token: list[Token]) -> None:
        self.tokens: list[Token] = token
        self.index = 0

    def peek(self):
        if self.index >= len(self.tokens):
            return Token(TokenKind.Eof, "")
        return self.tokens[self.index]

    def next(self):
        cur = self.peek()
        self.index += 1
        return cur

    def expect_kind(self, *kind: TokenKind):
        if self.peek().kind not in kind:
            raise SyntaxError(f"expect {kind} got {self.peek().kind}")
        return self.next()

    def expect_punc(self, s):
        if self.peek().val != s:
            raise SyntaxError(f"expect {s} got {self.peek().val}")
        return self.next()

    def parse_ident(self) -> StrExpr:
        return StrExpr(self.expect_kind(TokenKind.NakedString).val)

    def parse_expr(self) -> Expr:
        """Parse Expr := KvExpr | FnExpr | NakedStr."""
        token = self.peek()
        if token.kind == TokenKind.NormalString:
            return StrExpr(self.next().val)
        if token.kind != TokenKind.NakedString:
            raise SyntaxError(f"expect expression got {token.kind}")

        value = self.parse_ident()
        if self.peek().val == "=":
            self.next()
            return KvExpr(value, self.parse_expr())
        if self.peek().val == "(":
            return self.parse_call(value)
        return value

    def parse_call(self, fn: StrExpr | None = None) -> FnExpr:
        """Parse FnExpr := NakedStr '(' ArgsList? ')' ."""
        if fn is None:
            fn = self.parse_ident()
        self.expect_punc("(")
        args: list[Expr] = []
        if self.peek().val == ")":
            self.next()
            return FnExpr(fn, args)
        args.append(self.parse_expr())
        while self.peek().val == ",":
            self.next()
            if self.peek().val == ")":
                break
            args.append(self.parse_expr())
        self.expect_punc(")")
        return FnExpr(fn, args)

    def parse_func(self) -> FnExpr:
        """Parse a complete statement and reject trailing tokens."""
        result = self.parse_call()
        self.expect_kind(TokenKind.Eof)
        return result


def main():
    x = Parser(tokenize("json(key='abc', array(array=10), array)"))
    print(x.parse_func())


if __name__ == "__main__":
    main()
