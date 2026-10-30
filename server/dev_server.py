"""Dev server: SQLite backend, auto-creates tables."""
import asyncio
from pathlib import Path

from sqlalchemy.ext.asyncio import create_async_engine

from magbi.config import Settings
from magbi.metadata.models import Base
from magbi.storage.credentials import generate_key

DATA_DIR = Path("data")
DB_PATH = DATA_DIR / "dev.db"

settings = Settings(
    environment="dev",
    database_url=f"sqlite+aiosqlite:///{DB_PATH}",
    duckdb_data_dir=DATA_DIR / "datasets",
    credential_key=generate_key(),
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
