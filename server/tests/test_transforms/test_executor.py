import duckdb

from magbi.transforms.executor import preview
from magbi.transforms.steps import parse_steps


def _sales() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute('CREATE TABLE "Sales" ("Manager" VARCHAR, "Amount" INTEGER)')
    con.execute("INSERT INTO \"Sales\" VALUES ('Ann', 1), (NULL, 2), ('Bea', 3)")
    return con


def test_fill_down_follows_the_folded_sort() -> None:
    result = preview(
        _sales(),
        "Sales",
        ("Manager", "Amount"),
        parse_steps(
            [
                {
                    "type": "sortRows",
                    "columns": [{"column": "Amount", "direction": "asc"}],
                },
                {"type": "fillDown", "columns": ["Manager"]},
            ]
        ),
    )
    assert result["foldBoundary"] == 1
    assert result["rows"] == [["Ann", 1], ["Ann", 2], ["Bea", 3]]


def test_unpivot_and_pivot_round_trip_the_values() -> None:
    con = duckdb.connect()
    con.execute('CREATE TABLE "Months" ("Id" INTEGER, "Jan" INTEGER, "Feb" INTEGER)')
    con.execute('INSERT INTO "Months" VALUES (1, 2, 3)')
    melted = preview(
        con,
        "Months",
        ("Id", "Jan", "Feb"),
        parse_steps(
            [
                {
                    "type": "unpivot",
                    "idColumns": ["Id"],
                    "valueColumns": ["Jan", "Feb"],
                    "attributeName": "Month",
                    "valueName": "Amount",
                }
            ]
        ),
    )
    assert melted["rows"] == [[1, "Jan", 2], [1, "Feb", 3]]
    con.execute('CREATE TABLE "Long" ("Id" INTEGER, "Month" VARCHAR, "Amount" INTEGER)')
    con.execute("INSERT INTO \"Long\" VALUES (1, 'Jan', 2), (1, 'Feb', 3)")
    wide = preview(
        con,
        "Long",
        ("Id", "Month", "Amount"),
        parse_steps(
            [
                {
                    "type": "pivot",
                    "keyColumn": "Month",
                    "valueColumn": "Amount",
                    "aggregate": "sum",
                }
            ]
        ),
    )
    assert wide["rows"] == [[1, 2, 3]]
    assert [column["name"] for column in wide["columns"]] == ["Id", "Jan", "Feb"]
