"""Application settings loaded from environment."""

from pathlib import Path
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings

from magbi.storage.credentials import CredentialError, parse_key

DEFAULT_JWT_SECRET = "change-me-in-production"


class Settings(BaseSettings):
    environment: Literal["dev", "test", "prod"] = "dev"
    database_url: str = "postgresql+asyncpg://magbi:magbi@localhost:5432/magbi"
    redis_url: str = "redis://localhost:6379/0"
    duckdb_data_dir: Path = Path("data/datasets")
    duckdb_archive_versions: int = 5
    credential_key: str = ""
    jwt_secret: str = DEFAULT_JWT_SECRET
    jwt_algorithm: str = "HS256"
    jwt_private_key_pem: str = ""
    jwt_public_key_pem: str = ""
    access_token_ttl_minutes: int = 60
    embed_token_ttl_minutes: int = 15
    bootstrap_admin_email: str = ""
    bootstrap_admin_password: str = ""
    max_query_timeout_seconds: int = 30
    max_concurrent_refreshes: int = 10
    # Until auth lands (Sprint 7) the admin API is open, so outside dev it stays off
    # unless explicitly enabled. Comma-separated host allow-list for connectors
    # (empty = any host).
    import_batch_size: int = 10_000
    insecure_admin_api: bool = False
    connector_allowed_hosts: str = ""

    model_config = {"env_prefix": "MAGBI_"}

    @model_validator(mode="after")
    def _validate_security(self) -> "Settings":
        if self.credential_key:
            try:
                parse_key(self.credential_key)
            except CredentialError as exc:
                raise ValueError(f"MAGBI_CREDENTIAL_KEY invalid: {exc}") from exc
        if self.import_batch_size < 1:
            raise ValueError("MAGBI_IMPORT_BATCH_SIZE must be >= 1")
        if self.duckdb_archive_versions < 0:
            raise ValueError("MAGBI_DUCKDB_ARCHIVE_VERSIONS must be >= 0")
        if self.environment != "dev":
            if not self.credential_key:
                raise ValueError(
                    "MAGBI_CREDENTIAL_KEY is required when environment is not dev"
                )
            if self.jwt_secret == DEFAULT_JWT_SECRET:
                raise ValueError(
                    "MAGBI_JWT_SECRET must be changed when environment is not dev"
                )
        return self


settings = Settings()
