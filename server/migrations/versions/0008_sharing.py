"""report shares, apps, subscriptions, alerts and notifications

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-31 13:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _fk(column: str, table: str, source: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint([column], [f"{table}.id"], name=op.f(f"fk_{source}_{column}_{table}"), ondelete="CASCADE")


def upgrade() -> None:
    op.create_table(
        "report_shares",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("report_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("shared_by", sa.String(length=320), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        _fk("report_id", "reports", "report_shares"),
        _fk("user_id", "users", "report_shares"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_report_shares")),
        sa.UniqueConstraint("report_id", "user_id", name="uq_report_shares_report_id_user_id"),
    )
    op.create_index(op.f("ix_report_shares_report_id"), "report_shares", ["report_id"])
    op.create_index(op.f("ix_report_shares_user_id"), "report_shares", ["user_id"])
    op.create_table(
        "apps",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_published", sa.Boolean(), nullable=False),
        sa.Column("updated_by", sa.String(length=320), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        _fk("workspace_id", "workspaces", "apps"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_apps")),
    )
    op.create_index(op.f("ix_apps_workspace_id"), "apps", ["workspace_id"])
    op.create_table(
        "app_reports",
        sa.Column("app_id", sa.Uuid(), nullable=False),
        sa.Column("report_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        _fk("app_id", "apps", "app_reports"),
        _fk("report_id", "reports", "app_reports"),
        sa.PrimaryKeyConstraint("app_id", "report_id", name=op.f("pk_app_reports")),
    )
    op.create_table(
        "app_audience",
        sa.Column("app_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        _fk("app_id", "apps", "app_audience"),
        _fk("user_id", "users", "app_audience"),
        sa.PrimaryKeyConstraint("app_id", "user_id", name=op.f("pk_app_audience")),
    )
    op.create_table(
        "subscriptions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("report_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("cron", sa.String(length=100), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("last_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        _fk("report_id", "reports", "subscriptions"),
        _fk("user_id", "users", "subscriptions"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_subscriptions")),
    )
    op.create_index(op.f("ix_subscriptions_report_id"), "subscriptions", ["report_id"])
    op.create_index(op.f("ix_subscriptions_user_id"), "subscriptions", ["user_id"])
    op.create_table(
        "alerts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("report_id", sa.Uuid(), nullable=False),
        sa.Column("visual_id", sa.String(length=200), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("condition", sa.String(length=10), nullable=False),
        sa.Column("threshold", sa.Float(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("last_value", sa.Float(), nullable=True),
        sa.Column("last_met", sa.Boolean(), nullable=False),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_fired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        _fk("report_id", "reports", "alerts"),
        _fk("user_id", "users", "alerts"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_alerts")),
    )
    op.create_index(op.f("ix_alerts_report_id"), "alerts", ["report_id"])
    op.create_index(op.f("ix_alerts_user_id"), "alerts", ["user_id"])
    op.create_table(
        "notifications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=50), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("link", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        _fk("user_id", "users", "notifications"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notifications")),
    )
    op.create_index(op.f("ix_notifications_user_id"), "notifications", ["user_id"])
    op.create_index(op.f("ix_notifications_created_at"), "notifications", ["created_at"])


def downgrade() -> None:
    for table in ("notifications", "alerts", "subscriptions", "app_audience", "app_reports", "apps", "report_shares"):
        op.drop_table(table)
