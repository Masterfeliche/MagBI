"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-10-29 14:12:16.502526
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

import magbi.metadata.models

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_log",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column(
            "at", magbi.metadata.models.UTCDateTime(timezone=True), nullable=False
        ),
        sa.Column("principal", sa.String(length=320), nullable=False),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("object_type", sa.String(length=50), nullable=False),
        sa.Column("object_id", sa.String(length=64), nullable=True),
        sa.Column(
            "detail",
            sa.JSON().with_variant(
                postgresql.JSONB(astext_type=sa.Text()), "postgresql"
            ),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(action) > 0", name=op.f("ck_audit_log_action_not_empty")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_log")),
    )
    with op.batch_alter_table("audit_log", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_audit_log_at"), ["at"], unique=False)
        batch_op.create_index(
            "ix_audit_log_object", ["object_type", "object_id"], unique=False
        )

    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            magbi.metadata.models.UTCDateTime(timezone=True),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )
    op.create_table(
        "workspaces",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            magbi.metadata.models.UTCDateTime(timezone=True),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workspaces")),
        sa.UniqueConstraint("name", name=op.f("uq_workspaces_name")),
    )
    op.create_table(
        "datasets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "mode",
            sa.Enum(
                "import",
                "direct_query",
                name="dataset_mode",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("current_version", sa.Integer(), nullable=False),
        sa.Column("schedule_cron", sa.String(length=100), nullable=True),
        sa.Column(
            "created_at",
            magbi.metadata.models.UTCDateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            magbi.metadata.models.UTCDateTime(timezone=True),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_datasets_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_datasets")),
        sa.UniqueConstraint(
            "workspace_id", "name", name="uq_datasets_workspace_id_name"
        ),
    )
    with op.batch_alter_table("datasets", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_datasets_workspace_id"), ["workspace_id"], unique=False
        )

    op.create_table(
        "workspace_members",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "role",
            sa.Enum(
                "admin",
                "editor",
                "viewer",
                "embed_only",
                name="role",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_workspace_members_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_workspace_members_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "workspace_id", "user_id", name=op.f("pk_workspace_members")
        ),
    )
    op.create_table(
        "reports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column(
            "definition",
            sa.JSON().with_variant(
                postgresql.JSONB(astext_type=sa.Text()), "postgresql"
            ),
            nullable=False,
        ),
        sa.Column("is_published", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            magbi.metadata.models.UTCDateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            magbi.metadata.models.UTCDateTime(timezone=True),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["datasets.id"],
            name=op.f("fk_reports_dataset_id_datasets"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_reports_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reports")),
        sa.UniqueConstraint(
            "workspace_id", "name", name="uq_reports_workspace_id_name"
        ),
    )
    with op.batch_alter_table("reports", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_reports_dataset_id"), ["dataset_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_reports_workspace_id"), ["workspace_id"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("reports", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_reports_workspace_id"))
        batch_op.drop_index(batch_op.f("ix_reports_dataset_id"))

    op.drop_table("reports")
    op.drop_table("workspace_members")
    with op.batch_alter_table("datasets", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_datasets_workspace_id"))

    op.drop_table("datasets")
    op.drop_table("workspaces")
    op.drop_table("users")
    with op.batch_alter_table("audit_log", schema=None) as batch_op:
        batch_op.drop_index("ix_audit_log_object")
        batch_op.drop_index(batch_op.f("ix_audit_log_at"))

    op.drop_table("audit_log")
