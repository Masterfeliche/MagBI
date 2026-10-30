import duckdb

from magbi.transforms.errors import TransformError
from magbi.transforms.folding import fold
from magbi.transforms.steps import parse_steps


def _sales() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute('CREATE TABLE "Sales" ("Status" VARCHAR, "Amount" INTEGER)')
    con.execute("INSERT INTO \"Sales\" VALUES ('Open', 7), ('Done', 13), (NULL, 1)")
    return con


def test_filters_projection_rename_and_cast_run_in_duckdb() -> None:
    con = _sales()
    steps = parse_steps(
        [
            {
                "type": "filterRows",
                "column": "Status",
                "operator": "eq",
                "value": "Open",
            },
            {"type": "renameColumn", "oldName": "Amount", "newName": "Total"},
            {"type": "changeType", "column": "Total", "toType": "decimal"},
            {"type": "selectColumns", "columns": ["Total"]},
        ]
    )
    folded = fold("Sales", ("Status", "Amount"), steps)
    assert folded.folded_count == 4 and folded.remaining == ()
    assert con.execute(folded.sql).fetchall() == [(7.0,)]

    removed = fold(
        "Sales",
        ("Status", "Amount"),
        parse_steps([{"type": "removeRows", "column": "Status", "operator": "isNull"}]),
    )
    assert con.execute(removed.sql).fetchall() == [("Open", 7), ("Done", 13)]


def test_a_missing_column_is_rejected() -> None:
    steps = parse_steps(
        [{"type": "filterRows", "column": "Nope", "operator": "eq", "value": 1}]
    )
    try:
        fold("Sales", ("Amount",), steps)
    except TransformError as exc:
        assert exc.code == "UNKNOWN_COLUMN"
    else:
        raise AssertionError("expected UNKNOWN_COLUMN")
