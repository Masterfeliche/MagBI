import pytest

from magbi.refresh.parameters import ParameterError, bind_sql_parameters


def test_null_parameter_means_all() -> None:
    sql = "SELECT 1 WHERE (@category IS NULL OR Category = @category)"
    bound = bind_sql_parameters(sql, {"category": None})
    assert "@" not in bound
    assert "Category = NULL" in bound


def test_a_value_is_quoted_and_an_unknown_name_is_rejected() -> None:
    bound = bind_sql_parameters("SELECT @warehouse", {"warehouse": "O'Hare"})
    assert bound == "SELECT N'O''Hare'"
    with pytest.raises(ParameterError, match="unknown parameter"):
        bind_sql_parameters("SELECT @other", {"warehouse": None})
