"""report drafts

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-31 12:00:00.000000

Every existing report stays as it is: published definition, no draft.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "reports",
        sa.Column("draft_definition", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=True),
    )
    op.add_column("reports", sa.Column("draft_updated_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("reports", "draft_updated_at")
    op.drop_column("reports", "draft_definition")
