"""Join steps from a fact table to the tables a query mentions.

Paths come from ``query_path``. This module does not search the graph again.
"""

from __future__ import annotations

from magbi.engine.errors import QueryError
from magbi.model.relationships import query_path
from magbi.model.schema import DatasetDefinition, ModelSchemaError, RelationshipDef


def join_steps(
    model: DatasetDefinition, fact: str, needed: tuple[str, ...]
) -> tuple[tuple[RelationshipDef, str], ...]:
    """Relationships to walk, in order, and the table each one adds."""
    joined = {fact}
    steps: list[tuple[RelationshipDef, str]] = []
    for extra in dict.fromkeys(needed):
        if extra in joined or extra == fact:
            continue
        try:
            path = query_path(model, fact, extra)
        except ModelSchemaError as exc:
            raise _path_error(exc) from None
        cursor = fact
        for rel in path:
            nxt = rel.to.table if rel.from_.table == cursor else rel.from_.table
            if nxt not in joined:
                steps.append((rel, nxt))
                joined.add(nxt)
            cursor = nxt
    return tuple(steps)


def _path_error(exc: ModelSchemaError) -> QueryError:
    message = str(exc)
    lowered = message.lower()
    if "ambiguous" in lowered:
        code = "AMBIGUOUS_PATH"
    elif "no relationship" in lowered:
        code = "NO_RELATIONSHIP"
    elif "cycle" in lowered:
        code = "CYCLE"
    else:
        code = "NO_RELATIONSHIP"
    return QueryError(code, message)
