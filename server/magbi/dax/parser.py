"""Pratt parser for one DAX-lite expression.

Comparisons and ``IN`` do not chain: ``a = b = c`` is an error. ``AND`` binds
tighter than ``OR``, and a prefix ``NOT`` or ``-`` binds tighter than either.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias

from magbi.dax.errors import DaxError
from magbi.dax.functions import function_error
from magbi.dax.lexer import Token, TokenKind, tokenize

_INFIX: dict[TokenKind, int] = {
    TokenKind.OR: 1,
    TokenKind.OR_OP: 1,
    TokenKind.AND: 2,
    TokenKind.AND_OP: 2,
    TokenKind.EQ: 4,
    TokenKind.NEQ: 4,
    TokenKind.LT: 4,
    TokenKind.GT: 4,
    TokenKind.LTE: 4,
    TokenKind.GTE: 4,
    TokenKind.IN: 4,
    TokenKind.PLUS: 5,
    TokenKind.MINUS: 5,
    TokenKind.AMP: 5,
    TokenKind.STAR: 6,
    TokenKind.SLASH: 6,
}
_COMPARISON = frozenset(
    {
        TokenKind.EQ,
        TokenKind.NEQ,
        TokenKind.LT,
        TokenKind.GT,
        TokenKind.LTE,
        TokenKind.GTE,
        TokenKind.IN,
    }
)
_OP_TEXT = {
    TokenKind.OR: "or",
    TokenKind.OR_OP: "or",
    TokenKind.AND: "and",
    TokenKind.AND_OP: "and",
    TokenKind.EQ: "=",
    TokenKind.NEQ: "<>",
    TokenKind.LT: "<",
    TokenKind.GT: ">",
    TokenKind.LTE: "<=",
    TokenKind.GTE: ">=",
    TokenKind.PLUS: "+",
    TokenKind.MINUS: "-",
    TokenKind.AMP: "&",
    TokenKind.STAR: "*",
    TokenKind.SLASH: "/",
}


@dataclass(frozen=True, slots=True)
class NumberLit:
    value: int | float
    line: int
    col: int


@dataclass(frozen=True, slots=True)
class StringLit:
    value: str
    line: int
    col: int


@dataclass(frozen=True, slots=True)
class BoolLit:
    value: bool
    line: int
    col: int


@dataclass(frozen=True, slots=True)
class ColumnRef:
    table: str
    column: str
    line: int
    col: int


@dataclass(frozen=True, slots=True)
class MeasureRef:
    name: str
    line: int
    col: int


@dataclass(frozen=True, slots=True)
class NameRef:
    name: str
    line: int
    col: int


@dataclass(frozen=True, slots=True)
class TableRef:
    """A physical table. The parser never emits this; the binder does."""

    name: str
    line: int
    col: int


@dataclass(frozen=True, slots=True)
class Call:
    name: str
    args: tuple[Expr, ...]
    line: int
    col: int


@dataclass(frozen=True, slots=True)
class Unary:
    op: str
    expr: Expr
    line: int
    col: int


@dataclass(frozen=True, slots=True)
class Binary:
    op: str
    left: Expr
    right: Expr
    line: int
    col: int


@dataclass(frozen=True, slots=True)
class InExpr:
    expr: Expr
    values: tuple[Expr, ...]
    line: int
    col: int


@dataclass(frozen=True, slots=True)
class VarBlock:
    bindings: tuple[tuple[str, Expr], ...]
    body: Expr
    line: int
    col: int


Expr: TypeAlias = (
    NumberLit
    | StringLit
    | BoolLit
    | ColumnRef
    | MeasureRef
    | NameRef
    | TableRef
    | Call
    | Unary
    | Binary
    | InExpr
    | VarBlock
)


def parse(source: str) -> Expr:
    """Parse one formula. Raises ``DaxError`` with a 1-based position."""
    return _Parser(tokenize(source)).parse()


class _Parser:
    def __init__(self, tokens: list[Token]) -> None:
        self._tokens = tokens
        self._i = 0

    def parse(self) -> Expr:
        expr = self._statement()
        if self._cur().kind is not TokenKind.EOF:
            token = self._cur()
            raise DaxError(
                "unexpected token after the expression", token.line, token.col
            )
        return expr

    def _cur(self) -> Token:
        return self._tokens[self._i]

    def _advance(self) -> Token:
        token = self._cur()
        if token.kind is not TokenKind.EOF:
            self._i += 1
        return token

    def _expect(self, kind: TokenKind, what: str) -> Token:
        token = self._cur()
        if token.kind is not kind:
            raise DaxError(f"expected {what}", token.line, token.col)
        return self._advance()

    def _statement(self) -> Expr:
        if self._cur().kind is TokenKind.VAR:
            return self._var()
        return self._expr(0)

    def _var(self) -> VarBlock:
        start = self._cur()
        bindings: list[tuple[str, Expr]] = []
        while self._cur().kind is TokenKind.VAR:
            self._advance()
            name = self._expect(TokenKind.IDENT, "a variable name")
            self._expect(TokenKind.EQ, "'='")
            bindings.append((name.text, self._statement()))
        self._expect(TokenKind.RETURN, "RETURN")
        if not bindings:
            raise DaxError("VAR needs a binding", start.line, start.col)
        return VarBlock(tuple(bindings), self._statement(), start.line, start.col)

    def _expr(self, min_prec: int) -> Expr:
        left = self._prefix()
        while True:
            token = self._cur()
            prec = _INFIX.get(token.kind)
            if prec is None or prec < min_prec:
                return left
            if token.kind in _COMPARISON and _is_comparison(left):
                raise DaxError("comparisons cannot be chained", token.line, token.col)
            if token.kind is TokenKind.IN:
                left = self._in_set(left, token)
                continue
            op = self._advance()
            left = Binary(
                _OP_TEXT[op.kind], left, self._expr(prec + 1), op.line, op.col
            )

    def _in_set(self, left: Expr, token: Token) -> InExpr:
        self._advance()
        self._expect(TokenKind.LBRACE, "'{'")
        values: list[Expr] = []
        if self._cur().kind is not TokenKind.RBRACE:
            values.append(self._statement())
            while self._cur().kind is TokenKind.COMMA:
                self._advance()
                values.append(self._statement())
        self._expect(TokenKind.RBRACE, "'}'")
        if not values:
            raise DaxError("IN needs at least one value", token.line, token.col)
        return InExpr(left, tuple(values), token.line, token.col)

    def _prefix(self) -> Expr:
        token = self._cur()
        if token.kind in {TokenKind.MINUS, TokenKind.PLUS}:
            self._advance()
            return Unary(_OP_TEXT[token.kind], self._expr(7), token.line, token.col)
        if token.kind is TokenKind.NOT:
            self._advance()
            return Unary("not", self._expr(3), token.line, token.col)
        return self._primary()

    def _primary(self) -> Expr:
        token = self._cur()
        if token.kind is TokenKind.NUMBER:
            self._advance()
            return NumberLit(_number(token.text), token.line, token.col)
        if token.kind is TokenKind.STRING:
            self._advance()
            return StringLit(token.text, token.line, token.col)
        if token.kind is TokenKind.TRUE:
            self._advance()
            return BoolLit(True, token.line, token.col)
        if token.kind is TokenKind.FALSE:
            self._advance()
            return BoolLit(False, token.line, token.col)
        if token.kind is TokenKind.COLUMN:
            self._advance()
            return ColumnRef(token.table, token.field, token.line, token.col)
        if token.kind is TokenKind.MEASURE:
            self._advance()
            return MeasureRef(token.field, token.line, token.col)
        if token.kind is TokenKind.IDENT:
            self._advance()
            if self._cur().kind is TokenKind.LPAREN:
                return self._call(token)
            return NameRef(token.text, token.line, token.col)
        if token.kind is TokenKind.LPAREN:
            self._advance()
            expr = self._statement()
            self._expect(TokenKind.RPAREN, "')'")
            return expr
        if token.kind is TokenKind.EOF:
            raise DaxError("unexpected end of formula", token.line, token.col)
        raise DaxError(
            f"unexpected {token.text or token.kind.value}", token.line, token.col
        )

    def _call(self, name: Token) -> Call:
        self._advance()
        args: list[Expr] = []
        if self._cur().kind is not TokenKind.RPAREN:
            args.append(self._argument())
            while self._cur().kind is TokenKind.COMMA:
                self._advance()
                args.append(self._argument())
        self._expect(TokenKind.RPAREN, "')'")
        problem = function_error(name.text)
        if problem is not None:
            raise DaxError(problem, name.line, name.col)
        return Call(name.text, tuple(args), name.line, name.col)

    def _argument(self) -> Expr:
        """An argument; an empty one, as in RANKX(t, e, , DESC), is BLANK()."""
        token = self._cur()
        if token.kind in (TokenKind.COMMA, TokenKind.RPAREN):
            return Call("BLANK", (), token.line, token.col)
        return self._statement()


def _is_comparison(expr: Expr) -> bool:
    if isinstance(expr, InExpr):
        return True
    return isinstance(expr, Binary) and expr.op in {"=", "<>", "<", ">", "<=", ">="}


def _number(text: str) -> int | float:
    if all(ch.isdigit() for ch in text):
        return int(text)
    return float(text)
