from __future__ import annotations

import pytest

from magbi.dax.errors import DaxError
from magbi.dax.parser import (
    Binary,
    BoolLit,
    Call,
    ColumnRef,
    InExpr,
    MeasureRef,
    NameRef,
    NumberLit,
    StringLit,
    Unary,
    VarBlock,
    parse,
)


def test_sum_of_a_column() -> None:
    tree = parse("SUM(Sales[Amount])")
    assert tree == Call("SUM", (ColumnRef("Sales", "Amount", 1, 5),), 1, 1)


def test_precedence_and_not() -> None:
    tree = parse("NOT 1 + 2 * 3 OR TRUE")
    assert isinstance(tree, Binary) and tree.op == "or"
    assert isinstance(tree.left, Unary) and tree.left.op == "not"
    added = tree.left.expr
    assert isinstance(added, Binary) and added.op == "+"
    assert added.left == NumberLit(1, 1, 5)
    assert added.right == Binary("*", NumberLit(2, 1, 9), NumberLit(3, 1, 13), 1, 11)
    assert tree.right == BoolLit(True, 1, 18)


def test_calculate_filter_and_measure() -> None:
    tree = parse('CALCULATE([Total], Sales[Status] = "Completed")')
    assert isinstance(tree, Call) and tree.name == "CALCULATE"
    assert tree.args[0] == MeasureRef("Total", 1, 11)
    filt = tree.args[1]
    assert isinstance(filt, Binary) and filt.op == "="
    assert filt.left == ColumnRef("Sales", "Status", 1, 20)
    assert isinstance(filt.right, StringLit) and filt.right.value == "Completed"


def test_in_set_var_and_divide() -> None:
    membership = parse('Sales[Status] IN { "A", "B" }')
    assert isinstance(membership, InExpr)
    assert [v.value for v in membership.values if isinstance(v, StringLit)] == [
        "A",
        "B",
    ]
    var = parse("VAR _x = 2 RETURN _x + 1")
    assert isinstance(var, VarBlock)
    assert var.bindings[0][0] == "_x"
    assert var.bindings[0][1] == NumberLit(2, 1, 10)
    assert isinstance(var.body, Binary) and isinstance(var.body.left, NameRef)
    divide = parse("DIVIDE([A], [B], 0)")
    assert isinstance(divide, Call) and len(divide.args) == 3


def test_keyword_and_operator_are_the_same_tree_shape() -> None:
    words = parse("TRUE AND FALSE")
    symbols = parse("TRUE && FALSE")
    assert isinstance(words, Binary) and isinstance(symbols, Binary)
    assert words.op == symbols.op == "and"


def test_chained_comparison_is_rejected() -> None:
    with pytest.raises(DaxError) as caught:
        parse("1 = 2 = 3")
    assert "chained" in caught.value.message
    assert caught.value.col == 7


def test_empty_and_unbalanced_input() -> None:
    with pytest.raises(DaxError, match="end of formula"):
        parse("   ")
    with pytest.raises(DaxError, match="expected"):
        parse("SUM(Sales[Amount]")
