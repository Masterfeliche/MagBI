"""Model validation. Errors block a save; warnings do not.

Rules that need the DAX parser are not run. ``checks_deferred`` names them so a
caller can see what was skipped. Structural problems that the schema already
rejects are reported with a stable code when a raw document is checked.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any, Literal

import duckdb
from pydantic import ValidationError

from magbi.model.relationships import find_cycle, join_path
from magbi.model.schema import DatasetDefinition, ModelSchemaError

DEFERRED = ("measure_expressions", "rls_expressions")

_SCHEMA_CODES: tuple[tuple[str, str], ...] = (
    ("defined more than once", "DUPLICATE_MEASURE"),
    ("duplicate table", "DUPLICATE_TABLE"),
    ("duplicate column", "DUPLICATE_COLUMN"),
    ("duplicate calculated column", "DUPLICATE_COLUMN"),
    ("duplicate measure", "DUPLICATE_MEASURE"),
    ("duplicate hierarchy", "DUPLICATE_HIERARCHY"),
    ("duplicate role", "DUPLICATE_ROLE"),
    ("more than one active", "MULTIPLE_ACTIVE"),
    ("more than one primary key", "MULTIPLE_KEYS"),
    ("does not exist", "MISSING_REFERENCE"),
    ("must be a primary key", "KEY_REQUIRED"),
    ("one-to-one", "KEY_REQUIRED"),
    ("cannot point a table at itself", "SELF_RELATIONSHIP"),
    ("needs date_column", "DATE_TABLE_COLUMN"),
    ("must be date or datetime", "DATE_TABLE_COLUMN"),
    ("is not a date table", "DATE_TABLE_COLUMN"),
    ("many-to-many", "UNSUPPORTED"),
    ("cross_filter", "UNSUPPORTED"),
)


@dataclass(frozen=True)
class Issue:
    code: str
    message: str
    severity: Literal["error", "warning"]


@dataclass
class ValidationReport:
    errors: list[Issue] = field(default_factory=list)
    warnings: list[Issue] = field(default_factory=list)
    checks_deferred: tuple[str, ...] = DEFERRED

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "errors": [_issue(i) for i in self.errors],
            "warnings": [_issue(i) for i in self.warnings],
            "checks_deferred": list(self.checks_deferred),
        }


def _issue(issue: Issue) -> dict[str, str]:
    return {"code": issue.code, "message": issue.message, "severity": issue.severity}


def _schema_code(message: str) -> str:
    lowered = message.lower()
    for needle, code in _SCHEMA_CODES:
        if needle in lowered:
            return code
    return "SCHEMA"


def _schema_issues(raw: dict[str, Any]) -> list[Issue] | DatasetDefinition:
    try:
        return DatasetDefinition.model_validate(raw)
    except ValidationError as exc:
        issues: list[Issue] = []
        seen: set[str] = set()
        for err in exc.errors():
            message = str(err.get("msg", "")).removeprefix("Value error, ")
            if message in seen:
                continue
            seen.add(message)
            loc = ".".join(str(part) for part in err.get("loc", ()))
            if err.get("type") == "literal_error" and (
                "cardinality" in loc or "cross_filter" in loc
            ):
                code = "UNSUPPORTED"
            else:
                code = _schema_code(message)
            issues.append(Issue(code, message, "error"))
        if not issues:
            issues.append(Issue("SCHEMA", "dataset definition is invalid", "error"))
        return issues


def validate_model(
    model: DatasetDefinition, live: duckdb.DuckDBPyConnection | None = None
) -> ValidationReport:
    """Graph checks on a document the schema has already accepted.

    ``live`` is the imported DuckDB file. Date-table gap checks run only when it
    is passed; otherwise a date table produces a warning that it was not checked.
    """
    report = ValidationReport()
    cycle = find_cycle(model)
    if cycle is not None:
        report.errors.append(
            Issue("CYCLE", "relationship cycle: " + " -> ".join(cycle), "error")
        )
    else:
        _ambiguous(model, report)
    _warnings(model, report)
    _date_tables(model, live, report)
    return report


def _ambiguous(model: DatasetDefinition, report: ValidationReport) -> None:
    names = [table.name for table in model.tables]
    reported: set[frozenset[str]] = set()
    for i, left in enumerate(names):
        for right in names[i + 1 :]:
            try:
                join_path(model, left, right)
            except ModelSchemaError as exc:
                message = str(exc)
                if "ambiguous" not in message:
                    continue  # no path is fine; the tables are simply unrelated
                pair = frozenset((left, right))
                if pair in reported:
                    continue
                reported.add(pair)
                report.errors.append(Issue("AMBIGUOUS_PATH", message, "error"))


def _warnings(model: DatasetDefinition, report: ValidationReport) -> None:
    linked = {rel.from_.table for rel in model.relationships} | {
        rel.to.table for rel in model.relationships
    }
    facts = {rel.from_.table for rel in model.relationships if rel.cardinality == "many-to-one"}
    for table in model.tables:
        if table.name not in linked:
            report.warnings.append(
                Issue(
                    "ISOLATED_TABLE",
                    f"table {table.name!r} has no relationships",
                    "warning",
                )
            )
        if table.name in facts and not table.measures:
            report.warnings.append(
                Issue(
                    "FACT_WITHOUT_MEASURES",
                    f"table {table.name!r} is on the many side of a relationship and has no measures",
                    "warning",
                )
            )
        if table.is_hidden and any(not measure.is_hidden for measure in table.measures):
            report.warnings.append(
                Issue(
                    "HIDDEN_TABLE_VISIBLE_MEASURE",
                    f"table {table.name!r} is hidden but has a visible measure",
                    "warning",
                )
            )
    for rel in model.relationships:
        source = model.table(rel.from_.table)
        column = source.column(rel.from_.column) if source is not None else None
        if column is not None and column.is_nullable and rel.join_type == "inner":
            report.warnings.append(
                Issue(
                    "NULLABLE_INNER_JOIN",
                    f"{rel.from_.table}.{rel.from_.column} is nullable and the relationship uses an inner join",
                    "warning",
                )
            )


def _date_tables(
    model: DatasetDefinition,
    live: duckdb.DuckDBPyConnection | None,
    report: ValidationReport,
) -> None:
    for table in model.tables:
        if not table.is_date_table or table.date_column is None:
            continue
        if live is None:
            report.warnings.append(
                Issue(
                    "DATE_TABLE_NOT_CHECKED",
                    f"date table {table.name!r} was not checked against imported data",
                    "warning",
                )
            )
            continue
        quoted = _quote(table.name)
        exists = live.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = ?",
            [table.name],
        ).fetchone()
        if exists is None or exists[0] == 0:
            report.warnings.append(
                Issue(
                    "DATE_TABLE_NOT_IMPORTED",
                    f"date table {table.name!r} is not in the imported data yet",
                    "warning",
                )
            )
            continue
        column = _quote(table.date_column)
        row = live.execute(
            f"SELECT COUNT(*), COUNT(DISTINCT {column}), MIN({column}), MAX({column}) FROM {quoted}"
        ).fetchone()
        if row is None:
            continue
        count, distinct, low, high = int(row[0]), int(row[1]), row[2], row[3]
        if count != distinct:
            report.errors.append(
                Issue(
                    "DATE_TABLE_DUPLICATES",
                    f"date table {table.name!r} has duplicate dates",
                    "error",
                )
            )
        if isinstance(low, dt.datetime):
            low = low.date()
        if isinstance(high, dt.datetime):
            high = high.date()
        if isinstance(low, dt.date) and isinstance(high, dt.date):
            expected = (high - low).days + 1
            if count != expected:
                report.errors.append(
                    Issue(
                        "DATE_TABLE_GAPS",
                        f"date table {table.name!r} has {expected - count} missing dates "
                        f"between {low.isoformat()} and {high.isoformat()}",
                        "error",
                    )
                )


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def validate_document(
    raw: dict[str, Any], live: duckdb.DuckDBPyConnection | None = None
) -> ValidationReport:
    """Validate an untrusted document. Schema problems come back as errors."""
    built = _schema_issues(raw)
    if isinstance(built, list):
        return ValidationReport(errors=built)
    return validate_model(built, live)
