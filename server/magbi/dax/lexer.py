"""Tokenise a DAX-lite formula. Whitespace and comments are skipped.

Column references (`Table[Column]` or `'Table Name'[Column]`) and measure
references (`[Name]`) are single tokens. A name that is both a keyword and a
function (`AND`, `TRUE`, `BLANK`, …) stays an identifier when `(` follows it.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from magbi.dax.errors import DaxError

_KEYWORDS: dict[str, str] = {
    "var": "var",
    "return": "return",
    "in": "in",
    "not": "not",
    "and": "and",
    "or": "or",
    "true": "true",
    "false": "false",
}
# These are functions when called and keywords otherwise.
_CALLABLE = frozenset({"and", "or", "not", "true", "false", "blank"})


class TokenKind(StrEnum):
    NUMBER = "number"
    STRING = "string"
    IDENT = "ident"
    COLUMN = "column"
    MEASURE = "measure"
    TRUE = "true"
    FALSE = "false"
    VAR = "var"
    RETURN = "return"
    IN = "in"
    NOT = "not"
    AND = "and"
    OR = "or"
    PLUS = "plus"
    MINUS = "minus"
    STAR = "star"
    SLASH = "slash"
    AMP = "amp"
    EQ = "eq"
    NEQ = "neq"
    LT = "lt"
    GT = "gt"
    LTE = "lte"
    GTE = "gte"
    AND_OP = "and_op"
    OR_OP = "or_op"
    LPAREN = "lparen"
    RPAREN = "rparen"
    LBRACE = "lbrace"
    RBRACE = "rbrace"
    COMMA = "comma"
    DOT = "dot"
    EOF = "eof"


@dataclass(frozen=True, slots=True)
class Token:
    kind: TokenKind
    line: int
    col: int
    text: str = ""
    table: str = ""
    field: str = ""


def tokenize(source: str) -> list[Token]:
    """Return the tokens of ``source``, ending with ``EOF``."""
    return _Lexer(source).run()


class _Lexer:
    def __init__(self, source: str) -> None:
        self._s = source
        self._n = len(source)
        self._i = 0
        self._line = 1
        self._col = 1

    def run(self) -> list[Token]:
        tokens: list[Token] = []
        while True:
            self._skip()
            if self._i >= self._n:
                tokens.append(Token(TokenKind.EOF, self._line, self._col))
                return tokens
            tokens.append(self._one())

    def _peek(self, offset: int = 0) -> str:
        j = self._i + offset
        return self._s[j] if j < self._n else ""

    def _bump(self) -> str:
        ch = self._s[self._i]
        self._i += 1
        if ch == "\n":
            self._line += 1
            self._col = 1
        else:
            self._col += 1
        return ch

    def _skip(self) -> None:
        while self._i < self._n:
            ch = self._peek()
            if ch in " \t\r\n":
                self._bump()
                continue
            if ch == "/" and self._peek(1) == "/":
                while self._i < self._n and self._peek() != "\n":
                    self._bump()
                continue
            if ch == "/" and self._peek(1) == "*":
                line, col = self._line, self._col
                self._bump()
                self._bump()
                while not (self._peek() == "*" and self._peek(1) == "/"):
                    if self._i >= self._n:
                        raise DaxError("unterminated block comment", line, col)
                    self._bump()
                self._bump()
                self._bump()
                continue
            return

    def _one(self) -> Token:
        line, col = self._line, self._col
        ch = self._peek()
        if ch == '"':
            return self._string(line, col)
        if ch == "'":
            return self._quoted(line, col)
        if ch == "[":
            return self._bracket(line, col, table="")
        if ch.isdigit():
            return self._number(line, col)
        if ch.isascii() and (ch.isalpha() or ch == "_"):
            return self._word(line, col)
        symbol = self._symbol(line, col)
        if symbol is not None:
            return symbol
        raise DaxError(f"unexpected character {ch!r}", line, col)

    def _string(self, line: int, col: int) -> Token:
        self._bump()
        chars: list[str] = []
        while self._i < self._n:
            ch = self._bump()
            if ch == '"':
                if self._peek() == '"':
                    self._bump()
                    chars.append('"')
                    continue
                return Token(TokenKind.STRING, line, col, text="".join(chars))
            if ch == "\n":
                break
            chars.append(ch)
        raise DaxError("unterminated string", line, col)

    def _quoted(self, line: int, col: int) -> Token:
        self._bump()
        chars: list[str] = []
        while self._i < self._n:
            ch = self._bump()
            if ch == "'":
                if self._peek() == "'":
                    self._bump()
                    chars.append("'")
                    continue
                name = "".join(chars)
                if not name:
                    raise DaxError("empty table name", line, col)
                if self._peek() == "[":
                    return self._bracket(line, col, table=name)
                return Token(TokenKind.IDENT, line, col, text=name)
            if ch == "\n":
                break
            chars.append(ch)
        raise DaxError("unterminated quoted name", line, col)

    def _bracket(self, line: int, col: int, table: str) -> Token:
        if self._peek() != "[":
            raise DaxError("expected '['", line, col)
        self._bump()
        chars: list[str] = []
        while self._i < self._n and self._peek() not in "]\n":
            chars.append(self._bump())
        if self._peek() != "]":
            raise DaxError("unterminated bracket", line, col)
        self._bump()
        name = "".join(chars)
        if not name or name.strip() != name or not name.strip():
            raise DaxError("empty name in brackets", line, col)
        if table:
            return Token(TokenKind.COLUMN, line, col, table=table, field=name)
        return Token(TokenKind.MEASURE, line, col, field=name)

    def _number(self, line: int, col: int) -> Token:
        start = self._i
        while self._peek().isdigit():
            self._bump()
        if self._peek() == "." and self._peek(1).isdigit():
            self._bump()
            while self._peek().isdigit():
                self._bump()
        if self._peek() in {"e", "E"}:
            signed = self._peek(1) in {"+", "-"}
            if not self._peek(2 if signed else 1).isdigit():
                raise DaxError("number is missing its exponent", line, col)
            self._bump()
            if self._peek() in {"+", "-"}:
                self._bump()
            while self._peek().isdigit():
                self._bump()
        return Token(TokenKind.NUMBER, line, col, text=self._s[start : self._i])

    def _word(self, line: int, col: int) -> Token:
        start = self._i
        self._bump()
        while self._peek().isascii() and (
            self._peek().isalnum() or self._peek() == "_"
        ):
            self._bump()
        text = self._s[start : self._i]
        if self._peek() == "[":
            return self._bracket(line, col, table=text)
        key = text.casefold()
        if key in _CALLABLE and self._peek() == "(":
            return Token(TokenKind.IDENT, line, col, text=text)
        kind_name = _KEYWORDS.get(key)
        if kind_name is not None:
            return Token(TokenKind(kind_name), line, col, text=text)
        return Token(TokenKind.IDENT, line, col, text=text)

    def _symbol(self, line: int, col: int) -> Token | None:
        ch = self._peek()
        two = ch + self._peek(1)
        paired = {
            "<>": TokenKind.NEQ,
            "<=": TokenKind.LTE,
            ">=": TokenKind.GTE,
            "&&": TokenKind.AND_OP,
            "||": TokenKind.OR_OP,
        }
        if two in paired:
            self._bump()
            self._bump()
            return Token(paired[two], line, col, text=two)
        single = {
            "+": TokenKind.PLUS,
            "-": TokenKind.MINUS,
            "*": TokenKind.STAR,
            "/": TokenKind.SLASH,
            "&": TokenKind.AMP,
            "=": TokenKind.EQ,
            "<": TokenKind.LT,
            ">": TokenKind.GT,
            "(": TokenKind.LPAREN,
            ")": TokenKind.RPAREN,
            "{": TokenKind.LBRACE,
            "}": TokenKind.RBRACE,
            ",": TokenKind.COMMA,
            ".": TokenKind.DOT,
        }
        kind = single.get(ch)
        if kind is None:
            return None
        self._bump()
        return Token(kind, line, col, text=ch)
