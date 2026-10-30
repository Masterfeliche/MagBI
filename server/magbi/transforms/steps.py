"""Transform steps. JSON field names match the import-pipeline spec.

``uppercase`` and ``lowercase`` are separate types. ``groupBy`` is included.
The definition does not store a recipe; the caller sends the list.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from magbi.transforms.errors import TransformError

_OPS = Literal[
    "eq",
    "neq",
    "gt",
    "gte",
    "lt",
    "lte",
    "contains",
    "startsWith",
    "endsWith",
    "isNull",
    "isNotNull",
]


class _Step(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class FilterRowsStep(_Step):
    type: Literal["filterRows"]
    column: str = Field(min_length=1)
    operator: _OPS
    value: Any | None = None


class RemoveRowsStep(_Step):
    type: Literal["removeRows"]
    column: str = Field(min_length=1)
    operator: _OPS
    value: Any | None = None


class SelectColumnsStep(_Step):
    type: Literal["selectColumns"]
    columns: list[str] = Field(min_length=1)


class RemoveColumnsStep(_Step):
    type: Literal["removeColumns"]
    columns: list[str] = Field(min_length=1)


class RenameColumnStep(_Step):
    type: Literal["renameColumn"]
    old_name: str = Field(alias="oldName", min_length=1)
    new_name: str = Field(alias="newName", min_length=1)


class ChangeTypeStep(_Step):
    type: Literal["changeType"]
    column: str = Field(min_length=1)
    to_type: Literal["string", "integer", "decimal", "date", "datetime", "boolean"] = (
        Field(alias="toType")
    )


class AddColumnStep(_Step):
    type: Literal["addColumn"]
    name: str = Field(min_length=1)
    expression: str = Field(min_length=1)
    data_type: str | None = Field(default=None, alias="dataType")


class ReplaceValuesStep(_Step):
    type: Literal["replaceValues"]
    column: str = Field(min_length=1)
    find: Any
    replace_with: Any = Field(alias="replaceWith")


class FillDownStep(_Step):
    type: Literal["fillDown"]
    columns: list[str] = Field(min_length=1)


class FillValueStep(_Step):
    type: Literal["fillValue"]
    column: str = Field(min_length=1)
    value: Any


class SplitColumnStep(_Step):
    type: Literal["splitColumn"]
    column: str = Field(min_length=1)
    delimiter: str = Field(min_length=1)
    new_column_names: list[str] = Field(alias="newColumnNames", min_length=1)


class MergeColumnsStep(_Step):
    type: Literal["mergeColumns"]
    columns: list[str] = Field(min_length=2)
    separator: str
    new_column_name: str = Field(alias="newColumnName", min_length=1)


class TrimTextStep(_Step):
    type: Literal["trimText"]
    column: str = Field(min_length=1)


class UppercaseStep(_Step):
    type: Literal["uppercase"]
    column: str = Field(min_length=1)


class LowercaseStep(_Step):
    type: Literal["lowercase"]
    column: str = Field(min_length=1)


class ExtractDateStep(_Step):
    type: Literal["extractDate"]
    column: str = Field(min_length=1)
    part: Literal["year", "month", "day"]
    name: str | None = None


class SortKey(_Step):
    column: str = Field(min_length=1)
    direction: Literal["asc", "desc"] = "asc"


class SortRowsStep(_Step):
    type: Literal["sortRows"]
    columns: list[SortKey] = Field(min_length=1)


class DistinctRowsStep(_Step):
    type: Literal["distinctRows"]
    columns: list[str] | None = None


class TopNStep(_Step):
    type: Literal["topN"]
    count: int = Field(ge=0)
    order_by: str = Field(alias="orderBy", min_length=1)
    direction: Literal["asc", "desc"] = "desc"


class UnpivotStep(_Step):
    type: Literal["unpivot"]
    id_columns: list[str] = Field(alias="idColumns")
    value_columns: list[str] = Field(alias="valueColumns", min_length=1)
    attribute_name: str = Field(alias="attributeName", min_length=1)
    value_name: str = Field(alias="valueName", min_length=1)


class PivotStep(_Step):
    type: Literal["pivot"]
    key_column: str = Field(alias="keyColumn", min_length=1)
    value_column: str = Field(alias="valueColumn", min_length=1)
    aggregate: Literal["sum", "min", "max", "count"] = "sum"


class Aggregation(_Step):
    column: str = Field(min_length=1)
    function: Literal["sum", "avg", "min", "max", "count", "countDistinct"]
    alias: str = Field(min_length=1)


class GroupByStep(_Step):
    type: Literal["groupBy"]
    group_columns: list[str] = Field(alias="groupColumns")
    aggregations: list[Aggregation] = Field(min_length=1)


TransformStep = Annotated[
    FilterRowsStep
    | RemoveRowsStep
    | SelectColumnsStep
    | RemoveColumnsStep
    | RenameColumnStep
    | ChangeTypeStep
    | AddColumnStep
    | ReplaceValuesStep
    | FillDownStep
    | FillValueStep
    | SplitColumnStep
    | MergeColumnsStep
    | TrimTextStep
    | UppercaseStep
    | LowercaseStep
    | ExtractDateStep
    | SortRowsStep
    | DistinctRowsStep
    | TopNStep
    | UnpivotStep
    | PivotStep
    | GroupByStep,
    Field(discriminator="type"),
]

_ADAPTER: TypeAdapter[TransformStep] = TypeAdapter(TransformStep)

STEP_TYPES = frozenset(
    {
        "filterRows",
        "removeRows",
        "selectColumns",
        "removeColumns",
        "renameColumn",
        "changeType",
        "addColumn",
        "replaceValues",
        "fillDown",
        "fillValue",
        "splitColumn",
        "mergeColumns",
        "trimText",
        "uppercase",
        "lowercase",
        "extractDate",
        "sortRows",
        "distinctRows",
        "topN",
        "unpivot",
        "pivot",
        "groupBy",
    }
)


def parse_step(raw: dict[str, Any]) -> TransformStep:
    """Validate one step. Unknown fields and unknown types are rejected."""
    try:
        return _ADAPTER.validate_python(raw)
    except ValidationError as exc:
        raise TransformError("TRANSFORM_STEP", _message(exc)) from None


def parse_steps(raw: list[dict[str, Any]]) -> tuple[TransformStep, ...]:
    return tuple(parse_step(item) for item in raw)


def _message(exc: ValidationError) -> str:
    item = exc.errors()[0]
    message = str(item.get("msg", "invalid step")).removeprefix("Value error, ")
    loc = ".".join(str(part) for part in item.get("loc", ()))
    if loc:
        return f"{loc}: {message}"
    return message
