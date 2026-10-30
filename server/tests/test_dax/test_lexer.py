from __future__ import annotations

import pytest

from magbi.dax.errors import DaxError
from magbi.dax.lexer import TokenKind, tokenize


def kinds(source: str) -> list[TokenKind]:
    return [token.kind for token in tokenize(source) if token.kind is not TokenKind.EOF]


def test_a_measure_call_is_ident_column_and_parens() -> None:
    tokens = tokenize("SUM(Sales[Amount])")
    assert [(t.kind, t.text, t.table, t.field) for t in tokens[:-1]] == [
        (TokenKind.IDENT, "SUM", "", ""),
        (TokenKind.LPAREN, "(", "", ""),
        (TokenKind.COLUMN, "", "Sales", "Amount"),
        (TokenKind.RPAREN, ")", "", ""),
    ]
    assert tokens[-1].kind is TokenKind.EOF
    assert tokens[2].line == 1 and tokens[2].col == 5


def test_quoted_table_measure_ref_and_string() -> None:
    tokens = tokenize("""[Revenue] = 'Date Table'[Year] = \"it\"\"s\" // note""")
    assert [t.kind for t in tokens[:-1]] == [
        TokenKind.MEASURE,
        TokenKind.EQ,
        TokenKind.COLUMN,
        TokenKind.EQ,
        TokenKind.STRING,
    ]
    assert tokens[0].field == "Revenue"
    assert tokens[2].table == "Date Table" and tokens[2].field == "Year"
    assert tokens[4].text == 'it"s'


def test_numbers_keywords_and_operators() -> None:
    source = "VAR _x = 1.5e-2 RETURN _x <> TRUE && NOT FALSE || 42"
    assert kinds(source) == [
        TokenKind.VAR,
        TokenKind.IDENT,
        TokenKind.EQ,
        TokenKind.NUMBER,
        TokenKind.RETURN,
        TokenKind.IDENT,
        TokenKind.NEQ,
        TokenKind.TRUE,
        TokenKind.AND_OP,
        TokenKind.NOT,
        TokenKind.FALSE,
        TokenKind.OR_OP,
        TokenKind.NUMBER,
    ]
    assert tokenize(source)[3].text == "1.5e-2"


def test_callable_keywords_stay_identifiers() -> None:
    assert kinds("AND(TRUE(), BLANK())") == [
        TokenKind.IDENT,
        TokenKind.LPAREN,
        TokenKind.IDENT,
        TokenKind.LPAREN,
        TokenKind.RPAREN,
        TokenKind.COMMA,
        TokenKind.IDENT,
        TokenKind.LPAREN,
        TokenKind.RPAREN,
        TokenKind.RPAREN,
    ]
    assert tokenize("AND(TRUE(), BLANK())")[0].text == "AND"


def test_set_and_block_comment() -> None:
    assert kinds('Status IN { "A", "B" } /* hidden\n*/ + 1') == [
        TokenKind.IDENT,
        TokenKind.IN,
        TokenKind.LBRACE,
        TokenKind.STRING,
        TokenKind.COMMA,
        TokenKind.STRING,
        TokenKind.RBRACE,
        TokenKind.PLUS,
        TokenKind.NUMBER,
    ]


def test_second_line_is_reported() -> None:
    tokens = tokenize("SUM(\nSales[Amount])")
    column = next(t for t in tokens if t.kind is TokenKind.COLUMN)
    assert column.line == 2 and column.col == 1


@pytest.mark.parametrize(
    ("source", "message"),
    [
        ('"abc', "unterminated string"),
        ("/* forever", "unterminated block comment"),
        ("Sales[Amount", "unterminated bracket"),
        ("1e", "missing its exponent"),
        ("`", "unexpected character"),
        ("[]", "empty name"),
    ],
)
def test_lexer_errors_name_the_spot(source: str, message: str) -> None:
    with pytest.raises(DaxError) as caught:
        tokenize(source)
    assert message in caught.value.message
    assert caught.value.line == 1
