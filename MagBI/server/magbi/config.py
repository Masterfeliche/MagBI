"""Application settings loaded from environment."""

from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://magbi:magbi@localhost:5432/magbi"
    redis_url: str = "redis://localhost:6379/0"
    duckdb_data_dir: Path = Path("data/datasets")
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 60
    embed_token_ttl_minutes: int = 15
    max_query_timeout_seconds: int = 30
    max_concurrent_refreshes: int = 10

    model_config = {"env_prefix": "MAGBI_"}


settings = Settings()
