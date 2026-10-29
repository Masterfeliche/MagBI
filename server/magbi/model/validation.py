"""Model validation. Errors block a save; warnings do not.

Rules that need the DAX parser are not run. ``checks_deferred`` names them so a
caller can see what was skipped. Structural problems that the schema already
rejects are reported with a stable code when a raw document is checked.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

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


def validate_model(model: DatasetDefinition) -> ValidationReport:
    """Graph checks on a document the schema has already accepted."""
    report = ValidationReport()
    cycle = find_cycle(model)
    if cycle is not None:
        report.errors.append(
            Issue("CYCLE", "relationship cycle: " + " -> ".join(cycle), "error")
        )
        return report
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
    return report


def validate_document(raw: dict[str, Any]) -> ValidationReport:
    """Validate an untrusted document. Schema problems come back as errors."""
    built = _schema_issues(raw)
    if isinstance(built, list):
        return ValidationReport(errors=built)
    return validate_model(built)
