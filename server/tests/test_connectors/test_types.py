import duckdb
import pyarrow as pa
import pytest

from magbi.connectors.base import SourceColumn
from magbi.connectors.types import (
    DataType,
    arrow_schema,
    cast_map,
    normalise_type_name,
    plan_columns,
    plan_sqlserver_column,
    warnings,
)


def col(t: str, **kw: int | None) -> SourceColumn:
    return SourceColumn("c", t, **kw)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("sql_type", "data_type", "duckdb_type"),
    [
        ("tinyint", DataType.INTEGER, "BIGINT"),
        ("smallint", DataType.INTEGER, "BIGINT"),
        ("int", DataType.INTEGER, "BIGINT"),
        ("bigint", DataType.INTEGER, "BIGINT"),
        ("bit", DataType.BOOLEAN, "BOOLEAN"),
        ("float", DataType.DECIMAL, "DOUBLE"),
        ("real", DataType.DECIMAL, "DOUBLE"),
        ("char", DataType.STRING, "VARCHAR"),
        ("varchar", DataType.STRING, "VARCHAR"),
        ("nchar", DataType.STRING, "VARCHAR"),
        ("nvarchar", DataType.STRING, "VARCHAR"),
        ("text", DataType.STRING, "VARCHAR"),
        ("ntext", DataType.STRING, "VARCHAR"),
        ("uniqueidentifier", DataType.STRING, "VARCHAR"),
        ("date", DataType.DATE, "DATE"),
        ("datetime", DataType.DATETIME, "TIMESTAMP"),
        ("datetime2", DataType.DATETIME, "TIMESTAMP"),
        ("smalldatetime", DataType.DATETIME, "TIMESTAMP"),
        ("time", DataType.TIME, "TIME"),
        ("varbinary", DataType.BINARY, "BLOB"),
        ("binary", DataType.BINARY, "BLOB"),
        ("image", DataType.BINARY, "BLOB"),
        ("rowversion", DataType.BINARY, "BLOB"),
    ],
)
def test_supported_types(sql_type: str, data_type: DataType, duckdb_type: str) -> None:
    plan = plan_sqlserver_column(col(sql_type))
    assert plan.data_type is data_type
    assert plan.duckdb_type == duckdb_type
    assert plan.cast is None
    assert plan.warning is None


def test_decimal_uses_precision_and_scale() -> None:
    plan = plan_sqlserver_column(col("decimal", precision=18, scale=2))
    assert plan.arrow_type == pa.decimal128(18, 2)
    assert plan.duckdb_type == "DECIMAL(18,2)"
    assert plan_sqlserver_column(
        col("numeric", precision=38, scale=10)
    ).duckdb_type == ("DECIMAL(38,10)")


def test_decimal_defaults_when_unknown() -> None:
    assert plan_sqlserver_column(col("decimal")).duckdb_type == "DECIMAL(18,0)"


def test_decimal_over_38_falls_back_to_double_with_warning() -> None:
    plan = plan_sqlserver_column(col("decimal", precision=40, scale=2))
    assert plan.arrow_type == pa.float64()
    assert plan.duckdb_type == "DOUBLE"
    assert plan.warning and "precision" in plan.warning


def test_money_types() -> None:
    assert plan_sqlserver_column(col("money")).arrow_type == pa.decimal128(19, 4)
    assert plan_sqlserver_column(col("smallmoney")).arrow_type == pa.decimal128(10, 4)


def test_datetime2_above_microseconds_warns() -> None:
    assert plan_sqlserver_column(col("datetime2", scale=7)).warning
    assert plan_sqlserver_column(col("datetime2", scale=6)).warning is None
    assert plan_sqlserver_column(col("datetime", scale=3)).warning is None


def test_datetimeoffset_is_normalised_to_utc_in_source() -> None:
    plan = plan_sqlserver_column(col("datetimeoffset"))
    assert plan.cast == "utc_datetime"
    assert plan.arrow_type == pa.timestamp("us")
    assert plan.warning and "UTC" in plan.warning


@pytest.mark.parametrize(
    "t", ["xml", "geography", "geometry", "hierarchyid", "sql_variant", "mystery_type"]
)
def test_unsupported_types_become_text_with_warning(t: str) -> None:
    plan = plan_sqlserver_column(col(t))
    assert plan.data_type is DataType.STRING
    assert plan.cast == "string"
    assert plan.warning and t in plan.warning


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("NVARCHAR(50)", "nvarchar"), (" Decimal(18, 2) ", "decimal"), ("INT", "int")],
)
def test_normalise_type_name(raw: str, expected: str) -> None:
    assert normalise_type_name(raw) == expected


def test_helpers() -> None:
    columns = [
        SourceColumn("a", "int"),
        SourceColumn("b", "xml"),
        SourceColumn("c", "datetimeoffset"),
    ]
    plans = plan_columns(columns)
    assert [p.column for p in plans] == ["a", "b", "c"]
    assert cast_map(plans) == {"b": "string", "c": "utc_datetime"}
    assert len(warnings(plans)) == 2
    schema = arrow_schema(plans)
    assert schema.names == ["a", "b", "c"]
    assert schema.field("a").type == pa.int64()


@pytest.mark.parametrize(
    "sql_type",
    [
        "int",
        "bit",
        "float",
        "varchar",
        "date",
        "datetime2",
        "time",
        "varbinary",
        "money",
    ],
)
def test_arrow_and_duckdb_types_agree(sql_type: str) -> None:
    """Loading an Arrow table of the planned type into the planned DuckDB type works."""
    plan = plan_sqlserver_column(col(sql_type, precision=19, scale=4))
    table = pa.table({"c": pa.array([None], type=plan.arrow_type)})
    con = duckdb.connect()
    con.execute(f"CREATE TABLE t (c {plan.duckdb_type})")
    con.register("batch", table)
    con.execute("INSERT INTO t SELECT * FROM batch")
    assert con.execute("SELECT COUNT(*) FROM t").fetchone() == (1,)
