"""Relationship edits and join paths.

Paths treat an active relationship as an undirected link: the question is which
tables connect, not which way a filter flows. Inactive relationships are stored
and ignored. Two shortest paths of equal length are ambiguous. A cycle is
reported on its own, because a path search would otherwise hide it.
"""

from __future__ import annotations

import uuid
from collections import deque

from magbi.model.schema import DatasetDefinition, ModelSchemaError, RelationshipDef


def add_relationship(
    model: DatasetDefinition, relationship: RelationshipDef
) -> DatasetDefinition:
    """Return a new definition with ``relationship`` added. The input is unchanged."""
    payload = model.model_dump(mode="json", by_alias=True)
    payload["relationships"].append(relationship.model_dump(mode="json", by_alias=True))
    return DatasetDefinition.model_validate(payload)


def remove_relationship(
    model: DatasetDefinition, relationship_id: uuid.UUID
) -> DatasetDefinition:
    """Return a new definition without the relationship, or raise if it is absent."""
    payload = model.model_dump(mode="json", by_alias=True)
    kept = [r for r in payload["relationships"] if r["id"] != str(relationship_id)]
    if len(kept) == len(payload["relationships"]):
        raise ModelSchemaError(f"relationship {relationship_id} does not exist")
    payload["relationships"] = kept
    return DatasetDefinition.model_validate(payload)


def _edges(
    model: DatasetDefinition, *, both_ways: bool
) -> dict[str, list[tuple[str, RelationshipDef]]]:
    """Active relationships. Directed edges run from the many side to the one side."""
    graph: dict[str, list[tuple[str, RelationshipDef]]] = {
        t.name: [] for t in model.tables
    }
    for rel in model.relationships:
        if not rel.is_active:
            continue
        graph.setdefault(rel.from_.table, []).append((rel.to.table, rel))
        if both_ways:
            graph.setdefault(rel.to.table, []).append((rel.from_.table, rel))
    return graph


def find_cycle(model: DatasetDefinition) -> list[str] | None:
    """Tables on a directed cycle (many side toward the one side), or None.

    A length-2 cycle cannot occur: only one active relationship is allowed per
    pair of tables. A longer loop (A to B to C to A) can.
    """
    graph = _edges(model, both_ways=False)
    done: set[str] = set()

    def walk(node: str, stack: list[str]) -> list[str] | None:
        stack.append(node)
        for nxt, _rel in graph.get(node, []):
            if nxt in stack:
                return stack[stack.index(nxt) :] + [nxt]
            if nxt not in done:
                found = walk(nxt, stack)
                if found is not None:
                    return found
        stack.pop()
        done.add(node)
        return None

    for name in graph:
        if name not in done:
            found = walk(name, [])
            if found is not None:
                return found
    return None


def join_path(model: DatasetDefinition, start: str, end: str) -> list[RelationshipDef]:
    """The only shortest path between two tables, over active relationships."""
    if model.table(start) is None:
        raise ModelSchemaError(f"table {start!r} does not exist")
    if model.table(end) is None:
        raise ModelSchemaError(f"table {end!r} does not exist")
    cycle = find_cycle(model)
    if cycle is not None:
        raise ModelSchemaError("relationship cycle: " + " -> ".join(cycle))
    if start == end:
        return []

    graph = _edges(model, both_ways=True)
    distance = {start: 0}
    parents: dict[str, list[tuple[str, RelationshipDef]]] = {start: []}
    queue: deque[str] = deque([start])
    while queue:
        node = queue.popleft()
        for nxt, rel in graph.get(node, []):
            hop = distance[node] + 1
            if nxt not in distance:
                distance[nxt] = hop
                parents[nxt] = [(node, rel)]
                queue.append(nxt)
            elif distance[nxt] == hop:
                parents[nxt].append((node, rel))

    if end not in distance:
        raise ModelSchemaError(f"no relationship path from {start!r} to {end!r}")

    counts: dict[str, int] = {}

    def path_count(node: str) -> int:
        if node not in counts:
            counts[node] = (
                1
                if node == start
                else sum(path_count(parent) for parent, _rel in parents[node])
            )
        return counts[node]

    if path_count(end) > 1:
        raise ModelSchemaError(
            f"ambiguous relationship path from {start!r} to {end!r}; deactivate one"
        )

    path: list[RelationshipDef] = []
    node = end
    while node != start:
        parent, rel = parents[node][0]
        path.append(rel)
        node = parent
    path.reverse()
    return path
