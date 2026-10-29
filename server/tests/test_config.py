import pytest
from pydantic import ValidationError

from magbi.config import Settings
from magbi.storage.credentials import generate_key


def make(**kw: object) -> Settings:
    return Settings(**kw)  # type: ignore[arg-type]


def test_dev_defaults_are_allowed() -> None:
    s = make()
    assert s.environment == "dev"
    assert s.credential_key == ""


def test_invalid_key_rejected_even_in_dev() -> None:
    with pytest.raises(ValidationError, match="CREDENTIAL_KEY"):
        make(credential_key="short")


def test_prod_requires_credential_key() -> None:
    with pytest.raises(ValidationError, match="CREDENTIAL_KEY is required"):
        make(environment="prod", jwt_secret="x" * 32)


def test_prod_rejects_default_jwt_secret() -> None:
    with pytest.raises(ValidationError, match="JWT_SECRET"):
        make(environment="prod", credential_key=generate_key())


def test_prod_valid() -> None:
    s = make(environment="prod", credential_key=generate_key(), jwt_secret="s" * 32)
    assert s.environment == "prod"


def test_negative_archive_versions_rejected() -> None:
    with pytest.raises(ValidationError):
        make(duckdb_archive_versions=-1)


def test_env_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAGBI_MAX_QUERY_TIMEOUT_SECONDS", "7")
    assert make().max_query_timeout_seconds == 7
