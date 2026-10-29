import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

SERVER_DIR = Path(__file__).resolve().parents[2]
TABLES = {
    "audit_log",
    "datasets",
    "reports",
    "users",
    "workspace_members",
    "workspaces",
}


@pytest.fixture
def cfg(tmp_path: Path) -> tuple[Config, Path]:
    db = tmp_path / "meta.db"
    c = Config(str(SERVER_DIR / "alembic.ini"))
    c.set_main_option("script_location", str(SERVER_DIR / "migrations"))
    c.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db}")
    return c, db


def table_names(db: Path) -> set[str]:
    con = sqlite3.connect(db)
    try:
        rows = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    finally:
        con.close()
    return {r[0] for r in rows} - {"alembic_version"}


def test_upgrade_creates_schema(cfg: tuple[Config, Path]) -> None:
    c, db = cfg
    command.upgrade(c, "head")
    assert table_names(db) == TABLES


def test_downgrade_removes_schema(cfg: tuple[Config, Path]) -> None:
    c, db = cfg
    command.upgrade(c, "head")
    command.downgrade(c, "base")
    assert table_names(db) == set()


def test_models_match_migration(cfg: tuple[Config, Path]) -> None:
    c, _ = cfg
    command.upgrade(c, "head")
    command.check(c)  # raises if autogenerate would produce a new migration
