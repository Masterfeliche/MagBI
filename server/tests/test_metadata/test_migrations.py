import json
import sqlite3
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

SERVER_DIR = Path(__file__).resolve().parents[2]
TABLES = {
    "audit_log",
    "connections",
    "dataset_refreshes",
    "datasets",
    "reports",
    "service_tokens",
    "themes",
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


def test_import_spec_becomes_a_definition(cfg: tuple[Config, Path]) -> None:
    c, db = cfg
    command.upgrade(c, "0002")
    workspace_id, dataset_id = str(uuid.uuid4()), str(uuid.uuid4())
    spec = {
        "connection_id": str(uuid.uuid4()),
        "tables": [{"schema": "sales", "name": "orders", "target": "lines"}],
    }
    con = sqlite3.connect(db)
    con.execute(
        "INSERT INTO workspaces (id, name, created_at) VALUES (?, 'w', '2026-01-01')",
        (workspace_id,),
    )
    con.execute(
        "INSERT INTO datasets (id, workspace_id, name, mode, current_version, "
        "created_at, updated_at, import_spec) VALUES (?, ?, 'd', 'import', 0, "
        "'2026-01-01', '2026-01-01', ?)",
        (dataset_id, workspace_id, json.dumps(spec)),
    )
    con.commit()
    con.close()

    command.upgrade(c, "head")
    con = sqlite3.connect(db)
    definition, version = con.execute(
        "SELECT definition, model_version FROM datasets"
    ).fetchone()
    con.close()
    document = json.loads(definition)
    assert version == 1
    assert document["connection_id"] == spec["connection_id"]
    assert document["tables"][0]["name"] == "lines"
    assert document["tables"][0]["source"] == {
        "type": "table",
        "schema": "sales",
        "table": "orders",
        "database": None,
    }

    command.downgrade(c, "0002")
    con = sqlite3.connect(db)
    restored = json.loads(con.execute("SELECT import_spec FROM datasets").fetchone()[0])
    columns = {r[1] for r in con.execute("PRAGMA table_info(datasets)")}
    con.close()
    assert "definition" not in columns
    assert restored["tables"] == [
        {"schema": "sales", "name": "orders", "target": "lines"}
    ]


def test_models_match_migration(cfg: tuple[Config, Path]) -> None:
    c, _ = cfg
    command.upgrade(c, "head")
    command.check(c)  # raises if autogenerate would produce a new migration
