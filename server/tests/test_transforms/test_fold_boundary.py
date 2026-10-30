import duckdb

from magbi.transforms.folding import fold
from magbi.transforms.steps import parse_steps


def test_sort_distinct_top_and_group_fold() -> None:
    con = duckdb.connect()
    con.execute('CREATE TABLE "Sales" ("Status" VARCHAR, "Amount" INTEGER)')
    con.execute(
        "INSERT INTO \"Sales\" VALUES ('Open', 7), ('Open', 3), ('Done', 13), ('Done', 13)"
    )
    grouped = fold(
        "Sales",
        ("Status", "Amount"),
        parse_steps(
            [
                {
                    "type": "groupBy",
                    "groupColumns": ["Status"],
                    "aggregations": [
                        {"column": "Amount", "function": "sum", "alias": "Total"}
                    ],
                }
            ]
        ),
    )
    assert sorted(con.execute(grouped.sql).fetchall()) == [("Done", 26), ("Open", 10)]
    top = fold(
        "Sales",
        ("Status", "Amount"),
        parse_steps(
            [
                {
                    "type": "sortRows",
                    "columns": [{"column": "Amount", "direction": "asc"}],
                },
                {"type": "distinctRows"},
                {"type": "topN", "count": 1, "orderBy": "Amount", "direction": "desc"},
            ]
        ),
    )
    assert con.execute(top.sql).fetchone() == ("Done", 13)


def test_fill_pivot_and_unpivot_stop_the_fold() -> None:
    steps = parse_steps(
        [
            {"type": "filterRows", "column": "Amount", "operator": "gt", "value": 0},
            {"type": "fillDown", "columns": ["Status"]},
            {"type": "uppercase", "column": "Status"},
        ]
    )
    folded = fold("Sales", ("Status", "Amount"), steps)
    assert folded.folded_count == 1
    assert [step.type for step in folded.remaining] == ["fillDown", "uppercase"]
    for name in ("pivot", "unpivot"):
        body: dict[str, object] = (
            {"keyColumn": "Status", "valueColumn": "Amount"}
            if name == "pivot"
            else {
                "idColumns": ["Status"],
                "valueColumns": ["Amount"],
                "attributeName": "Field",
                "valueName": "Value",
            }
        )
        stopped = fold(
            "Sales", ("Status", "Amount"), parse_steps([{"type": name, **body}])
        )
        assert stopped.folded_count == 0 and stopped.remaining[0].type == name
