"""Dev server: SQLite backend, auto-creates tables."""
import asyncio
from pathlib import Path

from sqlalchemy.ext.asyncio import create_async_engine

from magbi.config import Settings
from magbi.metadata.models import Base
from magbi.storage.credentials import generate_key

DATA_DIR = Path("data")
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


async def create_tables() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    engine = create_async_engine(settings.database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(create_tables())

    import uvicorn

    from magbi.main import create_app

    app = create_app(settings)
    uvicorn.run(app, host="0.0.0.0", port=8000)
