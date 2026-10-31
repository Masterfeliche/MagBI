"""Dev server: SQLite backend, auto-creates tables.

MAGBI_DEV_DATA (default ``data``) and MAGBI_DEV_PORT (default 8000) let a second,
throwaway server run beside it, as the end-to-end suite does in CI.
"""
import asyncio
import os
from pathlib import Path

from sqlalchemy import Connection, inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from magbi.config import Settings
from magbi.metadata.models import Base
from magbi.storage.credentials import generate_key

DATA_DIR = Path(os.environ.get("MAGBI_DEV_DATA", "data"))
DB_PATH = DATA_DIR / "dev.db"
KEY_PATH = DATA_DIR / "dev-credential.key"


def _credential_key() -> str:
    """Keep one key across restarts, or saved connection passwords can't be read."""
    if KEY_PATH.is_file():
        return KEY_PATH.read_text().strip()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    key = generate_key()
    KEY_PATH.write_text(key)
    return key


settings = Settings(
    environment="dev",
    database_url=f"sqlite+aiosqlite:///{DB_PATH}",
    duckdb_data_dir=DATA_DIR / "datasets",
    credential_key=_credential_key(),
    jwt_secret="dev-secret-dev-secret-dev-secret-42",
    insecure_admin_api=True,
)


def _add_new_columns(conn: Connection) -> None:
    """create_all never alters a table: add any new nullable column the models gained.

    Production runs the Alembic migrations instead; this keeps the dev database usable.
    """
    existing = inspect(conn)
    for table in Base.metadata.sorted_tables:
        if not existing.has_table(table.name):
            continue
        have = {column["name"] for column in existing.get_columns(table.name)}
        for column in table.columns:
            if column.name not in have and column.nullable:
                kind = column.type.compile(dialect=conn.dialect)
                conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {kind}'))


async def create_tables() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    engine = create_async_engine(settings.database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_add_new_columns)
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(create_tables())

    import uvicorn

    from magbi.main import create_app

    app = create_app(settings)
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("MAGBI_DEV_PORT", "8000")))
