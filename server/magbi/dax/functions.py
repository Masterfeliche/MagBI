"""Which function names DAX-lite accepts.

The supported set is the Sprint 4 compiler. Names in ``UNSUPPORTED`` are real
DAX functions that this compiler will not implement; anything else is unknown.
Handlers that emit SQL arrive with the compiler.
"""

from __future__ import annotations

AGGREGATES = frozenset(
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

SUPPORTED = AGGREGATES | frozenset(
    {
        "divide",
        "if",
        "calculate",
        "all",
        "removefilters",
        "filter",
        "and",
        "or",
        "not",
        "true",
        "false",
        "blank",
        "isblank",
        "sameperiodlastyear",
        "dateadd",
        "totalytd",
    }
)

# Who is asking: allowed in row-level security rules, where the engine puts in the user's email.
IDENTITY = frozenset({"userprincipalname", "username"})

# Real DAX that this sprint rejects with a specific message, not "unknown".
UNSUPPORTED = frozenset(
    {
        "addcolumns",
        "summarize",
        "generate",
        "topn",
        "union",
        "except",
        "intersect",
        "datatable",
        "calendar",
        "earlier",
        "concatenatex",
        "rankx",
        "percentilex",
        "userelationship",
        "sumx",
        "averagex",
        "minx",
        "maxx",
        "countx",
        "related",
        "keepfilters",
        "allexcept",
        "values",
        "switch",
        "median",
        "selectedvalue",
        "hasonevalue",
        "isfiltered",
        "iferror",
        "coalesce",
        "abs",
        "round",
        "int",
        "mod",
        "power",
        "concatenate",
        "left",
        "right",
        "mid",
        "upper",
        "lower",
        "len",
        "format",
        "year",
        "month",
        "day",
        "today",
        "date",
        "datediff",
        "eomonth",
        "weekday",
        "totalqtd",
        "totalmtd",
        "datesytd",
        "previousmonth",
        "previousyear",
        "parallelperiod",
    }
)


def function_error(name: str) -> str | None:
    """A message when ``name`` cannot be called, or None when it is supported."""
    key = name.casefold()
    if key in SUPPORTED or key in IDENTITY:
        return None
    if key in UNSUPPORTED:
        return (
            f"{name} is a DAX function not supported in DAX-lite. "
            "Consider a SQL view for table expressions."
        )
    return f"Unknown function {name!r}. Check the spelling."
