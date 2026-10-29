"""Add and remove relationships. The schema module rejects an illegal result."""

from __future__ import annotations

import uuid

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
