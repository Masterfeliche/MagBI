"""The dataset definition: one JSON document per dataset (DATASET-MODEL-SPEC).

Stored in ``datasets.definition``. Field names are snake_case, matching the rest
of the API; the spec's TypeScript uses camelCase. Identity, timestamps and the
imported-data version live on the ``datasets`` row. This document is the model.

A document that fails these checks cannot be constructed. Checks that need the
DAX parser (Sprint 4) or row data (date-table gaps) live in ``validation.py``.
"""

from __future__ import annotations

import uuid
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from magbi.connectors.types import DataType

SCHEMA_VERSION: Literal["1.0"] = "1.0"
NAME_MAX = 128
EXPRESSION_MAX = 10_000
_DATE_TYPES = {DataType.DATE, DataType.DATETIME}


class ModelSchemaError(ValueError):
    """The document is structurally invalid. The message is safe to show."""


class AggregationType(StrEnum):
    SUM = "sum"
    AVERAGE = "average"
    COUNT = "count"
    DISTINCT_COUNT = "distinctCount"
    MIN = "min"
    MAX = "max"
    NONE = "none"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


def _name(value: str, what: str) -> str:
    name = value.strip()
    if not name or len(name) > NAME_MAX:
        raise ModelSchemaError(f"{what} name must be 1-{NAME_MAX} characters")
    if any(ord(ch) < 32 for ch in name):
        raise ModelSchemaError(f"{what} name contains control characters")
    return name


def _expression(value: str, what: str) -> str:
    text = value.strip()
    if not text:
        raise ModelSchemaError(f"{what} expression must not be empty")
    if len(text) > EXPRESSION_MAX:
        raise ModelSchemaError(
            f"{what} expression is longer than {EXPRESSION_MAX} characters"
        )
    return text


# -- sources -------------------------------------------------------------------


class SqlTableSource(_Model):
    type: Literal["table"] = "table"
    schema_: str = Field(alias="schema", min_length=1, max_length=NAME_MAX)
    table: str = Field(min_length=1, max_length=NAME_MAX)
    database: str | None = Field(default=None, max_length=NAME_MAX)


class SqlQuerySource(_Model):
    type: Literal["query"] = "query"
    sql: str = Field(min_length=1, max_length=EXPRESSION_MAX)
    description: str | None = Field(default=None, max_length=2000)


class CsvSource(_Model):
    type: Literal["csv"] = "csv"
    file_path: str = Field(min_length=1, max_length=500)
    delimiter: str = Field(default=",", min_length=1, max_length=8)
    has_header: bool = True


TableSource = Annotated[
    SqlTableSource | SqlQuerySource | CsvSource, Field(discriminator="type")
]


# -- columns, measures, hierarchies --------------------------------------------


class ColumnDef(_Model):
    name: str = Field(min_length=1, max_length=NAME_MAX)
    data_type: DataType
    description: str | None = Field(default=None, max_length=2000)
    source_column: str | None = Field(default=None, max_length=NAME_MAX)
    is_nullable: bool = True
    is_primary_key: bool = False
    is_foreign_key: bool = False
    display_name: str | None = Field(default=None, max_length=200)
    format: str | None = Field(default=None, max_length=50)
    is_hidden: bool = False
    sort_by_column: str | None = Field(default=None, max_length=NAME_MAX)
    default_aggregation: AggregationType | None = None

    @model_validator(mode="after")
    def _clean(self) -> ColumnDef:
        self.name = _name(self.name, "column")
        return self


class MeasureDef(_Model):
    """A stored formula. The expression is not parsed until Sprint 4."""

    name: str = Field(min_length=1, max_length=NAME_MAX)
    expression: str = Field(min_length=1, max_length=EXPRESSION_MAX)
    description: str | None = Field(default=None, max_length=2000)
    display_name: str | None = Field(default=None, max_length=200)
    display_folder: str | None = Field(default=None, max_length=200)
    format: str | None = Field(default=None, max_length=50)
    is_hidden: bool = False
    return_type: DataType | None = None

    @model_validator(mode="after")
    def _clean(self) -> MeasureDef:
        self.name = _name(self.name, "measure")
        if "[" in self.name or "]" in self.name:
            raise ModelSchemaError("measure name must not contain '[' or ']'")
        self.expression = _expression(self.expression, f"measure {self.name!r}")
        return self


class CalculatedColumnDef(_Model):
    """Stored only. Calculated columns are computed in a later sprint."""

    name: str = Field(min_length=1, max_length=NAME_MAX)
    expression: str = Field(min_length=1, max_length=EXPRESSION_MAX)
    data_type: DataType
    description: str | None = Field(default=None, max_length=2000)
    is_hidden: bool = False

    @model_validator(mode="after")
    def _clean(self) -> CalculatedColumnDef:
        self.name = _name(self.name, "calculated column")
        self.expression = _expression(
            self.expression, f"calculated column {self.name!r}"
        )
        return self


class HierarchyLevel(_Model):
    name: str = Field(min_length=1, max_length=NAME_MAX)
    column: str = Field(min_length=1, max_length=NAME_MAX)
    sort_by_column: str | None = Field(default=None, max_length=NAME_MAX)

    @model_validator(mode="after")
    def _clean(self) -> HierarchyLevel:
        self.name = _name(self.name, "hierarchy level")
        return self


class HierarchyDef(_Model):
    name: str = Field(min_length=1, max_length=NAME_MAX)
    description: str | None = Field(default=None, max_length=2000)
    levels: list[HierarchyLevel] = Field(min_length=1, max_length=16)

    @model_validator(mode="after")
    def _clean(self) -> HierarchyDef:
        self.name = _name(self.name, "hierarchy")
        return self


class TableDef(_Model):
    name: str = Field(min_length=1, max_length=NAME_MAX)
    description: str | None = Field(default=None, max_length=2000)
    source: TableSource | None = None
    columns: list[ColumnDef] = Field(default_factory=list, max_length=1000)
    measures: list[MeasureDef] = Field(default_factory=list, max_length=1000)
    calculated_columns: list[CalculatedColumnDef] = Field(
        default_factory=list, max_length=200
    )
    hierarchies: list[HierarchyDef] = Field(default_factory=list, max_length=50)
    is_date_table: bool = False
    date_column: str | None = Field(default=None, max_length=NAME_MAX)
    display_folder: str | None = Field(default=None, max_length=200)
    is_hidden: bool = False

    @model_validator(mode="after")
    def _consistent(self) -> TableDef:
        self.name = _name(self.name, "table")
        columns = _unique(
            (c.name for c in self.columns), f"column in table {self.name!r}"
        )
        _unique(
            (c.name for c in self.calculated_columns),
            f"calculated column in table {self.name!r}",
        )
        for calc in self.calculated_columns:
            if calc.name in columns:
                raise ModelSchemaError(
                    f"calculated column {calc.name!r} clashes with a column in table {self.name!r}"
                )
        _unique(
            (m.name.casefold() for m in self.measures),
            f"measure in table {self.name!r}",
        )
        _unique((h.name for h in self.hierarchies), f"hierarchy in table {self.name!r}")
        keys = [c.name for c in self.columns if c.is_primary_key]
        if len(keys) > 1:
            raise ModelSchemaError(
                f"table {self.name!r} has more than one primary key: {keys}"
            )
        for column in self.columns:
            if (
                column.sort_by_column is not None
                and column.sort_by_column not in columns
            ):
                raise ModelSchemaError(
                    f"column {self.name}.{column.name} sorts by {column.sort_by_column!r}, which does not exist"
                )
        for hierarchy in self.hierarchies:
            for level in hierarchy.levels:
                if level.column not in columns:
                    raise ModelSchemaError(
                        f"hierarchy {self.name}.{hierarchy.name} references column {level.column!r}, which does not exist"
                    )
                if (
                    level.sort_by_column is not None
                    and level.sort_by_column not in columns
                ):
                    raise ModelSchemaError(
                        f"hierarchy {self.name}.{hierarchy.name} sorts by {level.sort_by_column!r}, which does not exist"
                    )
        if self.is_date_table:
            if self.date_column is None:
                raise ModelSchemaError(f"date table {self.name!r} needs date_column")
            marked = next((c for c in self.columns if c.name == self.date_column), None)
            if marked is None:
                raise ModelSchemaError(
                    f"date table {self.name!r} date_column {self.date_column!r} does not exist"
                )
            if marked.data_type not in _DATE_TYPES:
                raise ModelSchemaError(
                    f"date table {self.name!r} date_column {self.date_column!r} must be date or datetime"
                )
        elif self.date_column is not None:
            raise ModelSchemaError(
                f"table {self.name!r} sets date_column but is not a date table"
            )
        return self

    def column(self, name: str) -> ColumnDef | None:
        return next((c for c in self.columns if c.name == name), None)

    def primary_key(self) -> ColumnDef | None:
        return next((c for c in self.columns if c.is_primary_key), None)


# -- relationships, security, the document -------------------------------------


class ColumnRef(_Model):
    table: str = Field(min_length=1, max_length=NAME_MAX)
    column: str = Field(min_length=1, max_length=NAME_MAX)


class RelationshipDef(_Model):
    """``from`` is the many side, ``to`` is the one side."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    name: str | None = Field(default=None, max_length=200)
    from_: ColumnRef = Field(alias="from")
    to: ColumnRef
    cardinality: Literal["many-to-one", "one-to-one"]
    cross_filter_direction: Literal["single"] = "single"
    is_active: bool = True
    join_type: Literal["inner", "left"] = "left"


class RlsTableFilter(_Model):
    table: str = Field(min_length=1, max_length=NAME_MAX)
    expression: str = Field(min_length=1, max_length=EXPRESSION_MAX)

    @model_validator(mode="after")
    def _clean(self) -> RlsTableFilter:
        self.expression = _expression(self.expression, "RLS")
        return self


class RlsRoleDef(_Model):
    """A row-level security role. ``members`` are the viewers it applies to, by email.

    Workspace editors and admins see every row, as in Power BI. Embed tokens name
    their roles themselves.
    """

    name: str = Field(min_length=1, max_length=NAME_MAX)
    description: str | None = Field(default=None, max_length=2000)
    table_filters: list[RlsTableFilter] = Field(min_length=1, max_length=100)
    members: list[str] = Field(default_factory=list, max_length=5000)

    @model_validator(mode="after")
    def _clean(self) -> RlsRoleDef:
        self.name = _name(self.name, "role")
        self.members = sorted({item.strip().lower() for item in self.members if item.strip()})
        return self


class DateTableConfig(_Model):
    auto_generate: bool = False
    fiscal_year_start_month: int = Field(default=1, ge=1, le=12)
    first_day_of_week: int = Field(default=0, ge=0, le=6)


class DatasetDefinition(_Model):
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    connection_id: uuid.UUID | None = None
    tables: list[TableDef] = Field(default_factory=list, max_length=500)
    relationships: list[RelationshipDef] = Field(default_factory=list, max_length=2000)
    roles: list[RlsRoleDef] = Field(default_factory=list, max_length=100)
    date_table: DateTableConfig = Field(default_factory=DateTableConfig)

    @model_validator(mode="after")
    def _consistent(self) -> DatasetDefinition:
        table_names = _unique((t.name for t in self.tables), "table")
        measure_names: list[str] = []
        for table in self.tables:
            for measure in table.measures:
                key = measure.name.casefold()
                if key in measure_names:
                    raise ModelSchemaError(
                        f"measure {measure.name!r} is defined more than once; names are unique across the dataset"
                    )
                measure_names.append(key)
        _unique((r.name for r in self.roles), "role")
        _unique((str(r.id) for r in self.relationships), "relationship id")
        active_pairs: set[frozenset[str]] = set()
        for rel in self.relationships:
            self._check_endpoint(rel.from_, table_names, "from")
            self._check_endpoint(rel.to, table_names, "to")
            if rel.from_.table == rel.to.table:
                raise ModelSchemaError("a relationship cannot point a table at itself")
            pair = frozenset((rel.from_.table, rel.to.table))
            if rel.is_active:
                if pair in active_pairs:
                    names = " and ".join(sorted(pair))
                    raise ModelSchemaError(
                        f"{names} have more than one active relationship; deactivate one"
                    )
                active_pairs.add(pair)
            to_column = self.table(rel.to.table).column(rel.to.column)  # type: ignore[union-attr]
            assert to_column is not None
            if not to_column.is_primary_key:
                raise ModelSchemaError(
                    f"relationship target {rel.to.table}.{rel.to.column} must be a primary key"
                )
            if rel.cardinality == "one-to-one":
                from_column = self.table(rel.from_.table).column(rel.from_.column)  # type: ignore[union-attr]
                assert from_column is not None
                if not from_column.is_primary_key:
                    raise ModelSchemaError(
                        f"one-to-one relationship needs a primary key on {rel.from_.table}.{rel.from_.column} too"
                    )
        for role in self.roles:
            for filt in role.table_filters:
                if filt.table not in table_names:
                    raise ModelSchemaError(
                        f"role {role.name!r} filters table {filt.table!r}, which does not exist"
                    )
        return self

    def _check_endpoint(self, ref: ColumnRef, tables: set[str], side: str) -> None:
        if ref.table not in tables:
            raise ModelSchemaError(
                f"relationship {side} side references table {ref.table!r}, which does not exist"
            )
        if self.table(ref.table).column(ref.column) is None:  # type: ignore[union-attr]
            raise ModelSchemaError(
                f"relationship references column {ref.table}.{ref.column}, which does not exist"
            )

    def table(self, name: str) -> TableDef | None:
        return next((t for t in self.tables if t.name == name), None)

    def measure(self, name: str) -> tuple[TableDef, MeasureDef] | None:
        key = name.casefold()
        for table in self.tables:
            for measure in table.measures:
                if measure.name.casefold() == key:
                    return table, measure
        return None

    def relationships_of(
        self, table: str, *, active_only: bool = False
    ) -> list[RelationshipDef]:
        return [
            r
            for r in self.relationships
            if table in (r.from_.table, r.to.table) and (r.is_active or not active_only)
        ]


def definition_from_import_spec(spec: dict[str, Any]) -> DatasetDefinition:
    """Build a definition from a Sprint 2 ``import_spec``.

    The import target becomes the table name. Columns are empty until the model
    is edited; a refresh still reads them from the source catalog.
    """
    tables: list[TableDef] = []
    seen: set[str] = set()
    for entry in spec.get("tables") or []:
        source_name = str(entry["name"])
        target = str(entry.get("target") or source_name)
        if target.casefold() in seen:
            raise ModelSchemaError(f"duplicate target table name {target!r}")
        seen.add(target.casefold())
        tables.append(
            TableDef(
                name=target,
                source=SqlTableSource.model_validate(
                    {
                        "type": "table",
                        "schema": str(entry["schema"]),
                        "table": source_name,
                    }
                ),
            )
        )
    raw_id = spec.get("connection_id")
    return DatasetDefinition(
        connection_id=uuid.UUID(str(raw_id)) if raw_id else None,
        tables=tables,
    )


def _unique(names: object, what: str) -> set[str]:
    seen: set[str] = set()
    for name in names:  # type: ignore[attr-defined]
        if name in seen:
            raise ModelSchemaError(f"duplicate {what} {name!r}")
        seen.add(name)
    return seen
