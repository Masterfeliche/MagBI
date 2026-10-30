import pytest

from magbi.connectors.errors import ConnectorError
from magbi.connectors.readonly import check_read_only


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT a FROM t",
        "  select a from t;  ",
        (
            "WITH r AS (SELECT 1 AS m UNION ALL SELECT m + 1 FROM r WHERE m < 5) "
            "SELECT m FROM r OPTION (MAXRECURSION 600)"
        ),
        "SELECT 'DELETE FROM x; DROP TABLE y' AS note FROM t",
        "SELECT [Update], \"Insert\" FROM t -- INSERT INTO z\n",
        "SELECT a /* EXEC xp_cmdshell */ FROM t",
        "SELECT N'≤ 90 d' AS w FROM t",
    ],
)
def test_read_only_selects_pass(sql: str) -> None:
    assert check_read_only(sql).upper().lstrip().startswith(("SELECT", "WITH"))


@pytest.mark.parametrize(
    ("sql", "reason"),
    [
        ("", "empty"),
        ("DELETE FROM t", "SELECT or WITH"),
        ("SELECT a INTO copy FROM t", "INTO"),
        ("SELECT a FROM t; DROP TABLE t", "one statement"),
        ("WITH x AS (SELECT 1 AS a) INSERT INTO t SELECT a FROM x", "INSERT"),
        ("SELECT * FROM OPENROWSET('SQLNCLI', 'x', 'SELECT 1')", "OPENROWSET"),
        ("SELECT a FROM t EXEC sp_who", "EXEC"),
    ],
)
def test_anything_that_may_write_is_refused(sql: str, reason: str) -> None:
    with pytest.raises(ConnectorError) as info:
        check_read_only(sql)
    assert reason in str(info.value)
