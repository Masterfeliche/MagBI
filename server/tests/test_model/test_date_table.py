import datetime as dt

import pytest

from magbi.model.date_table import generate_date_table, with_padding
from magbi.model.schema import DateTableConfig, ModelSchemaError


def test_every_day_is_present_including_the_leap_day() -> None:
    generated = generate_date_table(dt.date(2024, 2, 28), dt.date(2024, 3, 1))
    days = [row["Date"] for row in generated.rows]
    assert days == [dt.date(2024, 2, 28), dt.date(2024, 2, 29), dt.date(2024, 3, 1)]
    assert len({row["Date"] for row in generated.rows}) == len(generated.rows)
    assert generated.table.is_date_table and generated.table.date_column == "Date"
    assert generated.table.primary_key().name == "Date"  # type: ignore[union-attr]
    levels = [level.column for level in generated.table.hierarchies[0].levels]
    assert levels == ["Year", "Quarter", "Month", "Day"]


def test_calendar_columns_for_a_known_day() -> None:
    row = generate_date_table(dt.date(2026, 1, 15), dt.date(2026, 1, 15)).rows[0]
    assert row["Year"] == 2026
    assert row["Quarter"] == "Q1" and row["QuarterNumber"] == 1
    assert row["Month"] == "January" and row["MonthShort"] == "Jan"
    assert row["YearMonth"] == "2026-01" and row["Day"] == 15
    assert row["DayOfWeek"] == "Thursday" and row["DayOfWeekNumber"] == 3
    assert row["IsWeekend"] is False
    assert row["FiscalYear"] == 2026 and row["FiscalQuarter"] == "FQ1"


def test_fiscal_year_ends_in_the_named_year() -> None:
    config = DateTableConfig(fiscal_year_start_month=7)
    rows = {
        row["Date"]: row
        for row in generate_date_table(
            dt.date(2025, 6, 30), dt.date(2025, 7, 1), config
        ).rows
    }
    assert rows[dt.date(2025, 6, 30)]["FiscalYear"] == 2025
    assert rows[dt.date(2025, 6, 30)]["FiscalQuarter"] == "FQ4"
    assert rows[dt.date(2025, 7, 1)]["FiscalYear"] == 2026
    assert rows[dt.date(2025, 7, 1)]["FiscalQuarter"] == "FQ1"


def test_week_start_moves_the_weekend() -> None:
    sunday = DateTableConfig(first_day_of_week=6)
    rows = {
        row["Date"]: row
        for row in generate_date_table(
            dt.date(2026, 1, 18), dt.date(2026, 1, 19), sunday
        ).rows
    }
    # 18 Jan 2026 is a Sunday. With Sunday as day 0 it is a weekday, and Monday is the weekend.
    assert rows[dt.date(2026, 1, 18)]["DayOfWeekNumber"] == 0
    assert rows[dt.date(2026, 1, 18)]["IsWeekend"] is False
    assert rows[dt.date(2026, 1, 19)]["IsWeekend"] is False
    friday = generate_date_table(
        dt.date(2026, 1, 23), dt.date(2026, 1, 23), sunday
    ).rows[0]
    saturday = generate_date_table(
        dt.date(2026, 1, 24), dt.date(2026, 1, 24), sunday
    ).rows[0]
    assert friday["IsWeekend"] is True and saturday["IsWeekend"] is True


def test_padding_and_rejected_ranges() -> None:
    assert with_padding(dt.date(2024, 6, 1), dt.date(2025, 6, 1)) == (
        dt.date(2023, 6, 1),
        dt.date(2026, 6, 1),
    )
    with pytest.raises(ModelSchemaError, match="before"):
        generate_date_table(dt.date(2024, 2, 1), dt.date(2024, 1, 1))
    with pytest.raises(ModelSchemaError, match="200 years"):
        generate_date_table(dt.date(1000, 1, 1), dt.date(1500, 1, 1))


def test_a_full_year_has_no_gaps() -> None:
    generated = generate_date_table(dt.date(2024, 1, 1), dt.date(2024, 12, 31))
    assert len(generated.rows) == 366
    assert generated.rows[0]["WeekNumber"] == 1
    assert generated.rows[-1]["WeekNumber"] >= 52
