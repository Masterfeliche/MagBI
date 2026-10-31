"""Which function names DAX-lite accepts, and what each one takes.

``SIGNATURES`` is the catalogue the measure editor shows. Names in
``UNSUPPORTED`` are real DAX functions this compiler does not implement; each
gets a message saying so and, where there is one, what to use instead.
Anything else is unknown.
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

# Row-by-row aggregation over a table: SUMX(Sales, Sales[Qty] * RELATED(Product[Price])).
ITERATORS = frozenset({"sumx", "averagex", "minx", "maxx", "countx"})

# Questions about the current filter context, answered over the rows in it.
CONTEXT = frozenset({"selectedvalue", "hasonevalue", "isfiltered"})

# Time intelligence that replaces the date filter (CALCULATE modifiers) or wraps an expression.
TIME_MODIFIERS = frozenset({"sameperiodlastyear", "dateadd", "datesytd", "previousmonth", "previousyear", "parallelperiod"})
TIME_TOTALS = frozenset({"totalytd", "totalqtd", "totalmtd"})

SCALAR = frozenset(
    {
        "divide", "if", "switch", "iferror", "coalesce", "and", "or", "not", "true", "false", "blank", "isblank",
        "concatenate", "left", "right", "mid", "upper", "lower", "len", "format",
        "round", "abs", "int", "mod", "power",
        "year", "month", "day", "today", "date", "datediff", "eomonth", "weekday",
    }
)

SUPPORTED = (
    AGGREGATES
    | ITERATORS
    | CONTEXT
    | TIME_MODIFIERS
    | TIME_TOTALS
    | SCALAR
    | frozenset({"calculate", "all", "removefilters", "filter", "related", "rankx"})
)

# Who is asking: allowed in row-level security rules, where the engine puts in the user's email.
IDENTITY = frozenset({"userprincipalname", "username"})

# Bare words some functions take as an argument, such as DATEDIFF(…, …, MONTH).
KEYWORDS = frozenset({"day", "week", "month", "quarter", "year", "asc", "desc", "skip", "dense"})

_TABLE_EXPRESSIONS = "Table expressions aren't supported yet; use a SQL view or a calculated table in the source."
# Real DAX that is refused with a specific message, not "unknown".
UNSUPPORTED: dict[str, str] = {
    **{
        name: _TABLE_EXPRESSIONS
        for name in (
            "addcolumns", "summarize", "summarizecolumns", "generate", "union", "except", "intersect",
            "datatable", "calendar", "calendarauto", "values", "distinct", "crossjoin",
        )
    },
    "topn": "Use the visual's Top N filter for top or bottom items.",
    "earlier": "EARLIER isn't supported; write the row expression with RELATED or a calculated column.",
    "concatenatex": "CONCATENATEX isn't supported yet.",
    "percentilex": "PERCENTILEX isn't supported yet.",
    "median": "MEDIAN isn't supported yet.",
    "userelationship": "Only active relationships are used; USERELATIONSHIP isn't supported yet.",
    "keepfilters": "KEEPFILTERS isn't supported yet.",
    "allexcept": "ALLEXCEPT isn't supported yet; use ALL with the columns to clear.",
}

# What each supported function takes, for the measure editor. "…" means repeat.
SIGNATURES: dict[str, tuple[str, str]] = {
    "SUM": ("SUM(<column>)", "Adds up a numeric column."),
    "COUNT": ("COUNT(<column>)", "Counts the non-blank values in a column."),
    "COUNTA": ("COUNTA(<column>)", "Counts the non-blank values in a column."),
    "COUNTROWS": ("COUNTROWS(<table>)", "Counts the rows of a table."),
    "AVERAGE": ("AVERAGE(<column>)", "Averages a numeric column."),
    "MIN": ("MIN(<column>)", "The smallest value in a column."),
    "MAX": ("MAX(<column>)", "The largest value in a column."),
    "DISTINCTCOUNT": ("DISTINCTCOUNT(<column>)", "Counts the different values in a column."),
    "SUMX": ("SUMX(<table>, <row expression>)", "Adds up an expression worked out row by row."),
    "AVERAGEX": ("AVERAGEX(<table>, <row expression>)", "Averages an expression worked out row by row."),
    "MINX": ("MINX(<table>, <row expression>)", "The smallest value of a row-by-row expression."),
    "MAXX": ("MAXX(<table>, <row expression>)", "The largest value of a row-by-row expression."),
    "COUNTX": ("COUNTX(<table>, <row expression>)", "Counts the rows where the expression isn't blank."),
    "RELATED": ("RELATED(<column>)", "In a row expression, a column from the table on the one side of a relationship."),
    "CALCULATE": ("CALCULATE(<expression>, <filter>, …)", "Works out an expression with filters added or replaced."),
    "FILTER": ("FILTER(<table>, <condition>)", "Keeps the rows that meet a condition."),
    "ALL": ("ALL(<table or column>, …)", "Clears filters on a table or columns."),
    "REMOVEFILTERS": ("REMOVEFILTERS(<table or column>, …)", "Clears filters on a table or columns."),
    "SELECTEDVALUE": ("SELECTEDVALUE(<column>, [alternate])", "The column's value when exactly one is in context, else the alternate."),
    "HASONEVALUE": ("HASONEVALUE(<column>)", "TRUE when exactly one value of the column is in context."),
    "ISFILTERED": ("ISFILTERED(<column>)", "TRUE when a filter or slicer applies to the column."),
    "DIVIDE": ("DIVIDE(<numerator>, <denominator>, [alternate])", "Divides, giving the alternate (or blank) instead of dividing by zero."),
    "IF": ("IF(<condition>, <then>, [else])", "One of two results depending on a condition."),
    "SWITCH": ("SWITCH(<expression>, <value>, <result>, …, [else])", "The result for the first matching value. SWITCH(TRUE(), …) tests conditions."),
    "IFERROR": ("IFERROR(<expression>, <value if error>)", "The value instead of an error."),
    "COALESCE": ("COALESCE(<expression>, …)", "The first expression that isn't blank."),
    "AND": ("AND(<a>, <b>)", "TRUE when both are TRUE."),
    "OR": ("OR(<a>, <b>)", "TRUE when either is TRUE."),
    "NOT": ("NOT(<a>)", "The opposite."),
    "TRUE": ("TRUE()", "The value TRUE."),
    "FALSE": ("FALSE()", "The value FALSE."),
    "BLANK": ("BLANK()", "A blank value."),
    "ISBLANK": ("ISBLANK(<value>)", "TRUE when the value is blank."),
    "CONCATENATE": ("CONCATENATE(<text>, <text>)", "Joins two pieces of text."),
    "LEFT": ("LEFT(<text>, <count>)", "The first characters of the text."),
    "RIGHT": ("RIGHT(<text>, <count>)", "The last characters of the text."),
    "MID": ("MID(<text>, <start>, <count>)", "Characters from the middle of the text, counting from 1."),
    "UPPER": ("UPPER(<text>)", "The text in capitals."),
    "LOWER": ("LOWER(<text>)", "The text in small letters."),
    "LEN": ("LEN(<text>)", "How many characters the text has."),
    "FORMAT": ("FORMAT(<value>, <format>)", 'A number or date as text: "#,0", "0.0", "0%", "dd mmm yyyy", "mmm yy"…'),
    "ROUND": ("ROUND(<number>, <digits>)", "Rounds to that many decimal places."),
    "ABS": ("ABS(<number>)", "The number without its sign."),
    "INT": ("INT(<number>)", "Rounds down to a whole number."),
    "MOD": ("MOD(<number>, <divisor>)", "The remainder, with the sign of the divisor."),
    "POWER": ("POWER(<number>, <power>)", "The number raised to a power."),
    "YEAR": ("YEAR(<date>)", "The year of a date."),
    "MONTH": ("MONTH(<date>)", "The month number of a date, 1 to 12."),
    "DAY": ("DAY(<date>)", "The day of the month, 1 to 31."),
    "TODAY": ("TODAY()", "Today's date."),
    "DATE": ("DATE(<year>, <month>, <day>)", "A date from its parts."),
    "DATEDIFF": ("DATEDIFF(<start>, <end>, DAY|WEEK|MONTH|QUARTER|YEAR)", "How many interval boundaries lie between two dates."),
    "EOMONTH": ("EOMONTH(<date>, <months>)", "The last day of the month, that many months on."),
    "WEEKDAY": ("WEEKDAY(<date>, [1|2|3])", "Day of the week: 1 Sunday to 7 (type 1), 1 Monday to 7 (2), 0 Monday to 6 (3)."),
    "TOTALYTD": ("TOTALYTD(<expression>, <date column>)", "Year to date, from the fiscal year start."),
    "TOTALQTD": ("TOTALQTD(<expression>, <date column>)", "Quarter to date."),
    "TOTALMTD": ("TOTALMTD(<expression>, <date column>)", "Month to date."),
    "DATESYTD": ("DATESYTD(<date column>)", "In CALCULATE: the dates from the year start to the latest date in context."),
    "SAMEPERIODLASTYEAR": ("SAMEPERIODLASTYEAR(<date column>)", "In CALCULATE: the same dates one year earlier."),
    "DATEADD": ("DATEADD(<date column>, <count>, DAY|MONTH|QUARTER|YEAR)", "In CALCULATE: the dates moved by that many intervals."),
    "PREVIOUSMONTH": ("PREVIOUSMONTH(<date column>)", "In CALCULATE: the whole month before the dates in context."),
    "PREVIOUSYEAR": ("PREVIOUSYEAR(<date column>)", "In CALCULATE: the whole year before the dates in context."),
    "PARALLELPERIOD": ("PARALLELPERIOD(<date column>, <count>, MONTH|QUARTER|YEAR)", "In CALCULATE: whole periods moved by that many intervals."),
    "RANKX": ("RANKX(ALL(<table or column>), <expression>, , [ASC|DESC], [SKIP|DENSE])", "The rank of each row of the visual by the expression."),
}


def function_error(name: str) -> str | None:
    """A message when ``name`` cannot be called, or None when it is supported."""
    key = name.casefold()
    if key in SUPPORTED or key in IDENTITY:
        return None
    if key in UNSUPPORTED:
        return f"{name.upper()} is not supported in MagBI DAX yet. {UNSUPPORTED[key]}"
    return f"Unknown function {name!r}. Check the spelling."
