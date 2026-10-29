"""service tokens

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-29 20:50:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "service_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_service_tokens_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_service_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_service_tokens_token_hash")),
    )
    op.create_index(
        op.f("ix_service_tokens_workspace_id"), "service_tokens", ["workspace_id"]
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_service_tokens_workspace_id"), table_name="service_tokens")
    op.drop_table("service_tokens")
