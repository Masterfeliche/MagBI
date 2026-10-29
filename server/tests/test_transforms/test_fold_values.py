import duckdb

from magbi.transforms.errors import TransformError
from magbi.transforms.folding import fold
from magbi.transforms.steps import parse_steps


def test_replace_merge_and_lowercase_fold() -> None:
    con = duckdb.connect()
    con.execute(
        'CREATE TABLE "People" ("First" VARCHAR, "Last" VARCHAR, "Status" VARCHAR)'
    )
    con.execute("INSERT INTO \"People\" VALUES ('Bo', 'Lee', 'open')")
    folded = fold(
        "People",
        ("First", "Last", "Status"),
        parse_steps(
            [
                {"type": "lowercase", "column": "Status"},
                {
                    "type": "replaceValues",
                    "column": "Status",
                    "find": "open",
                    "replaceWith": "done",
                },
                {
                    "type": "mergeColumns",
                    "columns": ["First", "Last"],
                    "separator": " ",
                    "newColumnName": "Name",
                },
            ]
        ),
    )
    assert con.execute(folded.sql).fetchone() == ("Bo", "Lee", "done", "Bo Lee")


def test_value_steps_fold_and_a_statement_is_rejected() -> None:
    con = duckdb.connect()
    con.execute('CREATE TABLE "People" ("Name" VARCHAR, "sold" DATE, "Note" VARCHAR)')
    con.execute(
        "INSERT INTO \"People\" VALUES (' ada ', DATE '2024-03-15', NULL), ('bo', DATE '2024-01-02', 'x')"
    )
    steps = parse_steps(
        [
            {"type": "trimText", "column": "Name"},
            {"type": "uppercase", "column": "Name"},
            {"type": "fillValue", "column": "Note", "value": "-"},
            {"type": "extractDate", "column": "sold", "part": "year", "name": "Yr"},
            {"type": "addColumn", "name": "Tag", "expression": "Name || Note"},
            {
                "type": "splitColumn",
                "column": "Name",
                "delimiter": "A",
                "newColumnNames": ["Left"],
            },
        ]
    )
    folded = fold("People", ("Name", "sold", "Note"), steps)
    assert folded.folded_count == 6
    row = con.execute(folded.sql + " WHERE \"Name\" = 'ADA'").fetchone()
    assert row is not None
    assert row[0] == "ADA" and row[2] == "-" and row[3] == 2024 and row[4] == "ADA-"

    try:
        fold(
            "People",
            ("Name",),
            parse_steps(
                [
                    {
                        "type": "addColumn",
                        "name": "Bad",
                        "expression": "SELECT 1; SELECT 2",
                    }
                ]
            ),
        )
    except TransformError as exc:
        assert exc.code == "BAD_EXPRESSION"
    else:
        raise AssertionError("expected BAD_EXPRESSION")
