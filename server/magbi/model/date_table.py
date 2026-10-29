"""Auto-generated date dimension (DATASET-MODEL-SPEC 9.2).

One row per calendar day, with no gaps. The fiscal year is the calendar year in
which that fiscal year ends, so a year starting in July 2025 is fiscal 2026.
The weekend is the last two days of the configured week.
"""

from __future__ import annotations

import datetime as dt
from calendar import month_abbr, month_name
from dataclasses import dataclass

from magbi.connectors.types import DataType
from magbi.model.schema import (
    ColumnDef,
    DateTableConfig,
    HierarchyDef,
    HierarchyLevel,
    ModelSchemaError,
    TableDef,
)

MAX_SPAN_DAYS = 200 * 366
_WEEKDAYS = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)


@dataclass(frozen=True)
class GeneratedDateTable:
    table: TableDef
    rows: list[dict[str, object]]


def with_padding(start: dt.date, end: dt.date) -> tuple[dt.date, dt.date]:
    """One year of padding on each side, as the spec requires."""
    return start.replace(year=start.year - 1), end.replace(year=end.year + 1)


def generate_date_table(
    start: dt.date,
    end: dt.date,
    config: DateTableConfig | None = None,
    *,
    name: str = "Date",
) -> GeneratedDateTable:
    if end < start:
        raise ModelSchemaError("date table end is before its start")
    if (end - start).days > MAX_SPAN_DAYS:
        raise ModelSchemaError("date table range is longer than 200 years")
    cfg = config or DateTableConfig()
    rows = [_row(day, cfg) for day in _days(start, end)]
    table = TableDef(
        name=name,
        is_date_table=True,
        date_column="Date",
        is_hidden=False,
        columns=[
            ColumnDef(
                name="Date",
                data_type=DataType.DATE,
                is_nullable=False,
                is_primary_key=True,
            ),
            ColumnDef(name="Year", data_type=DataType.INTEGER, is_nullable=False),
            ColumnDef(
                name="Quarter",
                data_type=DataType.STRING,
                is_nullable=False,
                sort_by_column="QuarterNumber",
            ),
            ColumnDef(
                name="QuarterNumber",
                data_type=DataType.INTEGER,
                is_nullable=False,
                is_hidden=True,
            ),
            ColumnDef(
                name="Month",
                data_type=DataType.STRING,
                is_nullable=False,
                sort_by_column="MonthNumber",
            ),
            ColumnDef(
                name="MonthNumber",
                data_type=DataType.INTEGER,
                is_nullable=False,
                is_hidden=True,
            ),
            ColumnDef(name="MonthShort", data_type=DataType.STRING, is_nullable=False),
            ColumnDef(name="YearMonth", data_type=DataType.STRING, is_nullable=False),
            ColumnDef(name="Day", data_type=DataType.INTEGER, is_nullable=False),
            ColumnDef(
                name="DayOfWeek",
                data_type=DataType.STRING,
                is_nullable=False,
                sort_by_column="DayOfWeekNumber",
            ),
            ColumnDef(
                name="DayOfWeekNumber",
                data_type=DataType.INTEGER,
                is_nullable=False,
                is_hidden=True,
            ),
            ColumnDef(name="WeekNumber", data_type=DataType.INTEGER, is_nullable=False),
            ColumnDef(name="IsWeekend", data_type=DataType.BOOLEAN, is_nullable=False),
            ColumnDef(name="FiscalYear", data_type=DataType.INTEGER, is_nullable=False),
            ColumnDef(
                name="FiscalQuarter", data_type=DataType.STRING, is_nullable=False
            ),
        ],
        hierarchies=[
            HierarchyDef(
                name="DateHierarchy",
                levels=[
                    HierarchyLevel(name="Year", column="Year"),
                    HierarchyLevel(
                        name="Quarter", column="Quarter", sort_by_column="QuarterNumber"
                    ),
                    HierarchyLevel(
                        name="Month", column="Month", sort_by_column="MonthNumber"
                    ),
                    HierarchyLevel(name="Day", column="Day"),
                ],
            )
        ],
    )
    return GeneratedDateTable(table, rows)


def _days(start: dt.date, end: dt.date) -> list[dt.date]:
    count = (end - start).days + 1
    return [start + dt.timedelta(days=i) for i in range(count)]


def _row(day: dt.date, config: DateTableConfig) -> dict[str, object]:
    weekday = (day.weekday() - config.first_day_of_week) % 7
    quarter = (day.month - 1) // 3 + 1
    return {
        "Date": day,
        "Year": day.year,
        "Quarter": f"Q{quarter}",
        "QuarterNumber": quarter,
        "Month": month_name[day.month],
        "MonthNumber": day.month,
        "MonthShort": month_abbr[day.month],
        "YearMonth": f"{day.year:04d}-{day.month:02d}",
        "Day": day.day,
        "DayOfWeek": _WEEKDAYS[day.weekday()],
        "DayOfWeekNumber": weekday,
        "WeekNumber": _week_number(day, config.first_day_of_week),
        "IsWeekend": weekday >= 5,
        "FiscalYear": _fiscal_year(day, config.fiscal_year_start_month),
        "FiscalQuarter": _fiscal_quarter(day, config.fiscal_year_start_month),
    }


def _fiscal_year(day: dt.date, start_month: int) -> int:
    if start_month == 1 or day.month < start_month:
        return day.year
    return day.year + 1


def _fiscal_quarter(day: dt.date, start_month: int) -> str:
    offset = (day.month - start_month) % 12
    return f"FQ{offset // 3 + 1}"


def _week_number(day: dt.date, first_day: int) -> int:
    """Week 1 is the week containing 1 January, under the configured week start."""
    jan1 = dt.date(day.year, 1, 1)
    week1 = jan1 - dt.timedelta(days=(jan1.weekday() - first_day) % 7)
    if day < week1:
        return _week_number(dt.date(day.year - 1, 12, 31), first_day)
    return (day - week1).days // 7 + 1
