"""dataset definition

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-29 17:47:40.360832
"""

import json
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _json() -> sa.JSON:
    return sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def _load(value: Any) -> Any:
    if value is None or isinstance(value, dict):
        return value
    return json.loads(value)


def _assign(
    conn: sa.Connection, sql: str, row_id: Any, document: dict[str, Any]
) -> None:
    statement = (
        sql.replace(":doc", "CAST(:doc AS jsonb)")
        if conn.dialect.name == "postgresql"
        else sql
    )
    conn.execute(sa.text(statement), {"doc": json.dumps(document), "id": row_id})


def _copy_forward() -> None:
    from magbi.model.schema import definition_from_import_spec

    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id, import_spec FROM datasets")).fetchall()
    for row in rows:
        spec = _load(row[1])
        if not spec:
            continue
        document = definition_from_import_spec(spec).model_dump(
            mode="json", by_alias=True
        )
        _assign(
            conn,
            "UPDATE datasets SET definition = :doc WHERE id = :id",
            row[0],
            document,
        )


def _copy_back() -> None:
    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id, definition FROM datasets")).fetchall()
    for row in rows:
        document = _load(row[1]) or {}
        tables = []
        for table in document.get("tables") or []:
            source = table.get("source") or {}
            if source.get("type") == "table":
                tables.append(
                    {
                        "schema": source["schema"],
                        "name": source["table"],
                        "target": table["name"],
                    }
                )
        spec = {"connection_id": document.get("connection_id"), "tables": tables}
        _assign(
            conn, "UPDATE datasets SET import_spec = :doc WHERE id = :id", row[0], spec
        )


def upgrade() -> None:
    with op.batch_alter_table("datasets") as batch_op:
        batch_op.add_column(sa.Column("definition", _json(), nullable=True))
        batch_op.add_column(
            sa.Column("model_version", sa.Integer(), nullable=False, server_default="1")
        )
    _copy_forward()
    with op.batch_alter_table("datasets") as batch_op:
        batch_op.drop_column("import_spec")


def downgrade() -> None:
    with op.batch_alter_table("datasets") as batch_op:
        batch_op.add_column(sa.Column("import_spec", _json(), nullable=True))
    _copy_back()
    with op.batch_alter_table("datasets") as batch_op:
        batch_op.drop_column("model_version")
        batch_op.drop_column("definition")
