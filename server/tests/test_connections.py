import uuid

import pytest

from magbi.connections import REDACTED, ConnectionService, parse_allowed_hosts
from magbi.connectors.errors import ConnectorError, ErrorCode
from magbi.metadata.models import Connection
from magbi.storage.credentials import CredentialVault, generate_key

PASSWORD = "S3cret!pw;with}odd{chars"
CFG = {
    "host": "db.example.com",
    "database": "ERP",
    "authentication": "sql",
    "username": "bi",
    "password": PASSWORD,
}


@pytest.fixture
def vault() -> CredentialVault:
    return CredentialVault.from_encoded_key(generate_key())


def make_conn(
    svc: ConnectionService, cfg: dict[str, object], conn_id: uuid.UUID | None = None
) -> Connection:
    cid = conn_id or uuid.uuid4()
    public, secret = svc.prepare("sqlserver", cfg, connection_id=cid)
    return Connection(
        id=cid,
        workspace_id=uuid.uuid4(),
        name="erp",
        kind="sqlserver",
        config=public,
        secret_encrypted=secret,
    )


def test_password_is_encrypted_and_never_in_config(vault: CredentialVault) -> None:
    svc = ConnectionService(vault)
    conn = make_conn(svc, CFG)
    assert "password" not in conn.config
    assert conn.secret_encrypted and PASSWORD not in conn.secret_encrypted
    assert PASSWORD not in repr(conn.config)


def test_runtime_config_roundtrips_password(vault: CredentialVault) -> None:
    svc = ConnectionService(vault)
    conn = make_conn(svc, CFG)
    assert svc.runtime_config(conn)["password"] == PASSWORD


def test_secret_is_bound_to_connection_id(vault: CredentialVault) -> None:
    svc = ConnectionService(vault)
    conn = make_conn(svc, CFG)
    conn.id = uuid.uuid4()  # ciphertext moved to another row
    with pytest.raises(ConnectorError) as exc:
        svc.runtime_config(conn)
    assert exc.value.code == ErrorCode.INVALID_CONFIG
    assert PASSWORD not in str(exc.value)


def test_public_view_masks_password(vault: CredentialVault) -> None:
    svc = ConnectionService(vault)
    view = svc.public_view(make_conn(svc, CFG))
    assert view["config"]["password"] == REDACTED
    assert PASSWORD not in repr(view)
    assert "secret_encrypted" not in view


def test_integrated_auth_has_no_password_field(vault: CredentialVault) -> None:
    svc = ConnectionService(vault)
    cfg = {"host": "h", "database": "d", "authentication": "integrated"}
    conn = make_conn(svc, cfg)
    assert conn.secret_encrypted is None
    assert "password" not in svc.public_view(conn)["config"]


def test_update_with_redacted_or_missing_password_keeps_secret(
    vault: CredentialVault,
) -> None:
    svc = ConnectionService(vault)
    conn = make_conn(svc, CFG)
    original = conn.secret_encrypted
    for incoming in (
        {**CFG, "password": REDACTED},
        {k: v for k, v in CFG.items() if k != "password"},
    ):
        _, secret = svc.prepare(
            "sqlserver",
            {**incoming, "database": "Other"},
            connection_id=conn.id,
            existing_secret=original,
        )
        assert secret == original


def test_update_with_new_password_replaces_secret(vault: CredentialVault) -> None:
    svc = ConnectionService(vault)
    conn = make_conn(svc, CFG)
    public, secret = svc.prepare(
        "sqlserver",
        {**CFG, "password": "new"},
        connection_id=conn.id,
        existing_secret=conn.secret_encrypted,
    )
    conn.config, conn.secret_encrypted = public, secret
    assert svc.runtime_config(conn)["password"] == "new"


def test_storing_password_without_key_is_rejected() -> None:
    svc = ConnectionService(None)
    with pytest.raises(ConnectorError) as exc:
        svc.prepare("sqlserver", CFG, connection_id=uuid.uuid4())
    assert "MAGBI_CREDENTIAL_KEY" in str(exc.value)
    assert PASSWORD not in str(exc.value)


def test_decrypting_without_key_is_rejected(vault: CredentialVault) -> None:
    conn = make_conn(ConnectionService(vault), CFG)
    with pytest.raises(ConnectorError):
        ConnectionService(None).runtime_config(conn)


def test_validation_errors_never_echo_values(vault: CredentialVault) -> None:
    svc = ConnectionService(vault)
    bad = {**CFG, "port": PASSWORD}  # wrong type, value happens to be sensitive
    with pytest.raises(ConnectorError) as exc:
        svc.prepare("sqlserver", bad, connection_id=uuid.uuid4())
    assert exc.value.code == ErrorCode.INVALID_CONFIG
    assert "port" in str(exc.value) and PASSWORD not in str(exc.value)


def test_sql_auth_requires_credentials(vault: CredentialVault) -> None:
    svc = ConnectionService(vault)
    cfg = {"host": "h", "database": "d", "authentication": "sql"}
    with pytest.raises(ConnectorError) as exc:
        svc.prepare("sqlserver", cfg, connection_id=uuid.uuid4())
    assert exc.value.code == ErrorCode.INVALID_CONFIG


def test_unsupported_kind(vault: CredentialVault) -> None:
    with pytest.raises(ConnectorError) as exc:
        ConnectionService(vault).validate("oracle", {})
    assert exc.value.code == ErrorCode.UNSUPPORTED


def test_allow_list(vault: CredentialVault) -> None:
    svc = ConnectionService(vault, parse_allowed_hosts("DB.example.com, other"))
    svc.validate("sqlserver", CFG)
    svc.validate("sqlserver", {**CFG, "host": "other\\SQLEXPRESS"})  # instance ignored
    with pytest.raises(ConnectorError) as exc:
        svc.validate("sqlserver", {**CFG, "host": "169.254.169.254"})
    assert exc.value.code == ErrorCode.INVALID_CONFIG
    assert "not in the allowed host list" in str(exc.value)


def test_allow_list_is_enforced_at_connect_time_too(vault: CredentialVault) -> None:
    conn = make_conn(ConnectionService(vault), CFG)
    strict = ConnectionService(vault, ["somewhere-else"])
    with pytest.raises(ConnectorError):
        strict.runtime_config(conn)


def test_empty_allow_list_allows_any_host(vault: CredentialVault) -> None:
    ConnectionService(vault, []).validate("sqlserver", {**CFG, "host": "anything"})
    assert parse_allowed_hosts(" , ") == []


def test_connector_factory(vault: CredentialVault) -> None:
    svc = ConnectionService(vault)
    assert svc.connector_for("sqlserver").get_dialect() == "tsql"
    with pytest.raises(ConnectorError):
        svc.connector_for("nope")
    assert ConnectionService.supported_kinds() == ["mysql", "odata", "postgresql", "sqlserver"]
    assert [svc.connector_for(k).get_dialect() for k in ("postgresql", "mysql", "odata")] == ["postgres", "mysql", "odata"]


def test_new_kinds_validate_and_keep_their_secret(vault: CredentialVault) -> None:
    svc = ConnectionService(vault)
    for kind, cfg in (
        ("postgresql", {"host": "pg.example.com", "database": "erp", "username": "bi", "password": PASSWORD}),
        ("mysql", {"host": "my.example.com", "username": "bi", "password": PASSWORD}),
        ("odata", {"url": "https://data.example.org/odata/", "authentication": "bearer", "password": PASSWORD}),
    ):
        cid = uuid.uuid4()
        public, secret = svc.prepare(kind, cfg, connection_id=cid)
        assert "password" not in public and secret and PASSWORD not in secret
        conn = Connection(id=cid, workspace_id=uuid.uuid4(), name=kind, kind=kind, config=public, secret_encrypted=secret)
        assert svc.runtime_config(conn)["password"] == PASSWORD


def test_allowed_hosts_apply_to_a_web_source_url(vault: CredentialVault) -> None:
    svc = ConnectionService(vault, parse_allowed_hosts("data.example.org"))
    svc.validate("odata", {"url": "https://data.example.org/odata/"})
    with pytest.raises(ConnectorError) as exc:
        svc.validate("odata", {"url": "http://169.254.169.254/latest/"})
    assert exc.value.code == ErrorCode.INVALID_CONFIG and "allowed host" in exc.value.message
