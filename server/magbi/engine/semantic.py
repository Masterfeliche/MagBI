"""Semantic query contract and name binding.

The JSON shape is ``web/src/types/query.ts``. ``from`` is checked against the
model and is not the SQL FROM list.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from magbi.connectors.types import DataType
from magbi.engine.errors import QueryError
from magbi.model.schema import (
    CalculatedColumnDef,
    ColumnDef,
    DatasetDefinition,
    MeasureDef,
    TableDef,
)

DEFAULT_LIMIT = 10_000
MAX_LIMIT = 100_000

AGGREGATIONS = frozenset(
    {
        "sum",
        "count",
        "counta",
        "countrows",
        "average",
        "min",
        "max",
        "distinctcount",
    }
)


class QuerySource(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    table: str
    alias: str | None = Field(default=None, alias="as")


class QueryColumn(BaseModel):
    table: str
    column: str


class QueryMeasure(BaseModel):
    table: str
    measure: str


class QuerySelect(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    column: QueryColumn | None = None
    measure: QueryMeasure | None = None
    aggregation: str | None = None
    alias: str | None = Field(default=None, alias="as")

    @model_validator(mode="after")
    def _shape(self) -> QuerySelect:
        if self.column is not None and self.measure is not None:
            raise ValueError("a select entry is a column or a measure")
        if self.column is None and self.measure is None:
            raise ValueError("a select entry needs a column or a measure")
        if self.measure is not None and self.aggregation is not None:
            raise ValueError("a measure select cannot also set an aggregation")
        if self.aggregation is not None and self.column is None:
            raise ValueError("an aggregation needs a column")
        if (
            self.aggregation is not None
            and self.aggregation.casefold() not in AGGREGATIONS
        ):
            raise ValueError(f"aggregation {self.aggregation!r} is not supported")
        return self


class QueryFilter(BaseModel):
    column: QueryColumn
    operator: Literal[
        "eq",
        "ne",
        "gt",
        "gte",
        "lt",
        "lte",
        "in",
        "notIn",
        "contains",
        "startsWith",
        "isBlank",
        "isNotBlank",
    ]
    values: list[Any] | None = None


class QueryOrderBy(BaseModel):
    select: int = Field(ge=0)
    direction: Literal["asc", "desc"] = "asc"


class SemanticQuery(BaseModel):
    """One visual's question. Field names match the TypeScript contract."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    sources: list[QuerySource] = Field(default_factory=list, alias="from")
    select: list[QuerySelect] = Field(min_length=1)
    where: list[QueryFilter] = Field(default_factory=list)
    order_by: list[QueryOrderBy] = Field(default_factory=list, alias="orderBy")
    limit: int | None = Field(default=None, ge=0)
    include_totals: bool = Field(default=False, alias="includeTotals")


@dataclass(frozen=True, slots=True)
class GroupField:
    table: str
    column: str
    data_type: DataType
    alias: str


@dataclass(frozen=True, slots=True)
class MeasureField:
    """A stored measure, or an aggregation written against one column."""

    table: str
    name: str
    expression: str
    alias: str
    format: str | None
    data_type: DataType


@dataclass(frozen=True, slots=True)
class BoundQuery:
    fields: tuple[GroupField | MeasureField, ...]
    sources: tuple[str, ...]
    order_by: tuple[tuple[int, str], ...]
    limit: int | None
    include_totals: bool

    @property
    def groups(self) -> tuple[GroupField, ...]:
        return tuple(field for field in self.fields if isinstance(field, GroupField))

    @property
    def measures(self) -> tuple[MeasureField, ...]:
        return tuple(field for field in self.fields if isinstance(field, MeasureField))


def parse_query(raw: dict[str, Any]) -> SemanticQuery:
    """Validate the JSON shape. Unknown fields are rejected."""
    try:
        return SemanticQuery.model_validate(raw)
    except ValueError as exc:
        raise QueryError("QUERY_SHAPE", _first_message(exc)) from None


def bind_query(model: DatasetDefinition, query: SemanticQuery) -> BoundQuery:
    """Resolve every name. The model and the query are not modified."""
    sources = tuple(_table_name(model, source.table) for source in query.sources)
    fields: list[GroupField | MeasureField] = []
    aliases: set[str] = set()
    for item in query.select:
        if item.column is not None and item.aggregation is None:
            table_name = _table_name(model, item.column.table)
            column = _column(model, table_name, item.column.column)
            alias = _alias(item.alias or column.name, aliases)
            fields.append(GroupField(table_name, column.name, column.data_type, alias))
            continue
        fields.append(_measure_field(model, item, aliases))
    for ordering in query.order_by:
        if ordering.select >= len(query.select):
            raise QueryError(
                "QUERY_SHAPE",
                f"orderBy select {ordering.select} is outside the select list",
            )
    if query.limit is not None and query.limit > MAX_LIMIT:
        raise QueryError("QUERY_SHAPE", f"limit {query.limit} is above {MAX_LIMIT}")
    return BoundQuery(
        tuple(fields),
        sources,
        tuple((item.select, item.direction) for item in query.order_by),
        query.limit,
        query.include_totals,
    )


def _measure_field(
    model: DatasetDefinition, item: QuerySelect, aliases: set[str]
) -> MeasureField:
    if item.measure is not None:
        table_name = _table_name(model, item.measure.table)
        table = model.table(table_name)
        assert table is not None
        measure = _measure(table, item.measure.measure)
        alias = _alias(item.alias or measure.display_name or measure.name, aliases)
        data_type = measure.return_type or DataType.DECIMAL
        return MeasureField(
            table_name,
            measure.name,
            measure.expression,
            alias,
            measure.format,
            data_type,
        )
    assert item.column is not None and item.aggregation is not None
    table_name = _table_name(model, item.column.table)
    column = _column(model, table_name, item.column.column)
    function = item.aggregation.casefold()
    if function == "countrows":
        expression = f"COUNTROWS({_dax_name(table_name)})"
        data_type = DataType.INTEGER
    else:
        expression = (
            f"{function.upper()}({_dax_name(table_name)}[{_dax_field(column.name)}])"
        )
        data_type = _agg_type(function, column.data_type)
    alias = _alias(item.alias or f"{function.upper()} of {column.name}", aliases)
    return MeasureField(table_name, alias, expression, alias, None, data_type)


def _agg_type(function: str, column_type: DataType) -> DataType:
    if function in {"count", "counta", "distinctcount"}:
        return DataType.INTEGER
    if function == "average":
        return DataType.DECIMAL
    if function == "sum" and column_type == DataType.INTEGER:
        return DataType.INTEGER
    if function == "sum":
        return DataType.DECIMAL
    return column_type


def _alias(name: str, taken: set[str]) -> str:
    if name.casefold() in taken:
        raise QueryError("QUERY_SHAPE", f"select alias {name!r} is used more than once")
    taken.add(name.casefold())
    return name


def _table_name(model: DatasetDefinition, name: str) -> str:
    exact = model.table(name)
    if exact is not None:
        return exact.name
    folded = [
        table.name for table in model.tables if table.name.casefold() == name.casefold()
    ]
    if len(folded) == 1:
        return folded[0]
    if len(folded) > 1:
        raise QueryError("AMBIGUOUS_NAME", f"table {name!r} is ambiguous")
    raise QueryError("UNKNOWN_TABLE", f"table {name!r} does not exist")


def _column(
    model: DatasetDefinition, table_name: str, name: str
) -> ColumnDef | CalculatedColumnDef:
    table = model.table(table_name)
    assert table is not None
    exact = table.column(name)
    if exact is not None:
        return exact
    calculated = next((c for c in table.calculated_columns if c.name == name), None)
    if calculated is not None:
        return calculated
    folded_columns = [
        column for column in table.columns if column.name.casefold() == name.casefold()
    ]
    folded_calculated = [
        column
        for column in table.calculated_columns
        if column.name.casefold() == name.casefold()
    ]
    if len(folded_columns) + len(folded_calculated) == 1:
        if folded_columns:
            return folded_columns[0]
        return folded_calculated[0]
    if len(folded_columns) + len(folded_calculated) > 1:
        raise QueryError(
            "AMBIGUOUS_NAME", f"column {table_name!r}.{name!r} is ambiguous"
        )
    raise QueryError("UNKNOWN_COLUMN", f"column {table_name!r}.{name!r} does not exist")


def _measure(table: TableDef, name: str) -> MeasureDef:
    folded = [
        item for item in table.measures if item.name.casefold() == name.casefold()
    ]
    if len(folded) == 1:
        return folded[0]
    raise QueryError(
        "UNKNOWN_MEASURE", f"measure {table.name!r}[{name!r}] does not exist"
    )


def _dax_name(name: str) -> str:
    if name.isidentifier():
        return name
    return "'" + name.replace("'", "''") + "'"


def _dax_field(name: str) -> str:
    return name.replace("]", "]]")


def _first_message(exc: ValueError) -> str:
    text = str(exc)
    if "a select entry" in text or "aggregation" in text or "select alias" in text:
        return text
    errors = getattr(exc, "errors", None)
    if callable(errors):
        items = errors()
        if items:
            message = str(items[0].get("msg", text)).removeprefix("Value error, ")
            return message
    return text
