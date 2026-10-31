"""Connection service: validation, secret handling, redaction, host allow-list.

Passwords are encrypted with the credential vault, bound to the connection id
(AES-GCM associated data) so a ciphertext cannot be moved to another row. They
are stored only in ``connections.secret_encrypted``; ``config`` never holds one,
and API responses show ``"password": "***"``.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable, Mapping
from typing import Any
from urllib.parse import urlsplit

from pydantic import BaseModel, ValidationError

from magbi.connectors.base import Connector
from magbi.connectors.errors import ConnectorError, ErrorCode
from magbi.connectors.mysql import MySqlConfig, MySqlConnector
from magbi.connectors.odata import ODataConfig, ODataConnector
from magbi.connectors.postgresql import PostgresConfig, PostgresConnector
from magbi.connectors.sqlserver import SqlServerConfig, SqlServerConnector
from magbi.metadata.models import Connection
from magbi.storage.credentials import CredentialError, CredentialVault

REDACTED = "***"

_CONFIG_MODELS: dict[str, type[BaseModel]] = {
    "sqlserver": SqlServerConfig,
    "postgresql": PostgresConfig,
    "mysql": MySqlConfig,
    "odata": ODataConfig,
}
_CONNECTORS: dict[str, Callable[[], Connector]] = {
    "sqlserver": SqlServerConnector,
    "postgresql": PostgresConnector,
    "mysql": MySqlConnector,
    "odata": ODataConnector,
}


def host_of(config: Mapping[str, Any]) -> str:
    """The host a connection reaches: ``host``, or the host of ``url`` for web sources."""
    if config.get("url"):
        return urlsplit(str(config["url"])).hostname or ""
    return str(config.get("host", ""))


def parse_allowed_hosts(value: str) -> list[str]:
    return [h.strip().lower() for h in value.split(",") if h.strip()]


class ConnectionService:
    def __init__(
        self,
        vault: CredentialVault | None,
        allowed_hosts: Iterable[str] = (),
        connectors: Mapping[str, Callable[[], Connector]] | None = None,
    ) -> None:
        self._vault = vault
        self._allowed = [h.lower() for h in allowed_hosts]
        self._connectors = dict(connectors or _CONNECTORS)

    # -- validation -----------------------------------------------------------

    @staticmethod
    def supported_kinds() -> list[str]:
        return sorted(_CONFIG_MODELS)

    def check_host(self, host: str) -> None:
        """Enforce the optional allow-list (instance names such as ``h\\SQL`` ignored)."""
        if not self._allowed:
            return
        bare = host.split("\\", 1)[0].strip().lower()
        if bare not in self._allowed:
            raise ConnectorError(
                ErrorCode.INVALID_CONFIG,
                f"host {bare!r} is not in the allowed host list",
            )

    def validate(self, kind: str, config: Mapping[str, Any]) -> dict[str, Any]:
        """Validate a full connector config (password included) and the host.

        Error messages carry field names only, never submitted values.
        """
        model = _CONFIG_MODELS.get(kind)
        if model is None:
            raise ConnectorError(
                ErrorCode.UNSUPPORTED, f"unsupported connection kind {kind!r}"
            )
        try:
            model.model_validate(dict(config))
        except ValidationError as exc:
            problems = "; ".join(
                f"{'.'.join(str(p) for p in e['loc']) or 'config'}: {e['msg']}"
                for e in exc.errors()
            )
            raise ConnectorError(
                ErrorCode.INVALID_CONFIG, f"invalid config ({problems})"
            ) from None
        self.check_host(host_of(config))
        return dict(config)

    def connector_for(self, kind: str) -> Connector:
        factory = self._connectors.get(kind)
        if factory is None:
            raise ConnectorError(
                ErrorCode.UNSUPPORTED, f"unsupported connection kind {kind!r}"
            )
        return factory()

    # -- secrets --------------------------------------------------------------

    @staticmethod
    def _aad(connection_id: uuid.UUID) -> bytes:
        return str(connection_id).encode("ascii")

    def prepare(
        self,
        kind: str,
        config: Mapping[str, Any],
        *,
        connection_id: uuid.UUID,
        existing_secret: str | None = None,
    ) -> tuple[dict[str, Any], str | None]:
        """Split ``config`` into (public config, encrypted secret) for storage.

        A missing or redacted (``"***"``) password keeps ``existing_secret``.
        """
        incoming = dict(config)
        password = incoming.pop("password", None)
        keep_existing = password in (None, REDACTED)
        # validate with a placeholder so a kept secret does not fail the "needs password" rule
        probe = {**incoming, "password": "x" if keep_existing else password}
        self.validate(kind, probe)
        if keep_existing:
            return incoming, existing_secret
        if self._vault is None:
            raise ConnectorError(
                ErrorCode.INVALID_CONFIG,
                "cannot store a password: MAGBI_CREDENTIAL_KEY is not configured",
            )
        sealed = self._vault.encrypt(str(password), aad=self._aad(connection_id))
        return incoming, sealed

    def runtime_config(self, connection: Connection) -> dict[str, Any]:
        """Config with the decrypted password, for connecting. Never log or return it."""
        cfg = dict(connection.config)
        if connection.secret_encrypted:
            if self._vault is None:
                raise ConnectorError(
                    ErrorCode.INVALID_CONFIG,
                    "stored credentials require MAGBI_CREDENTIAL_KEY",
                )
            try:
                cfg["password"] = self._vault.decrypt(
                    connection.secret_encrypted, aad=self._aad(connection.id)
                )
            except CredentialError:
                raise ConnectorError(
                    ErrorCode.INVALID_CONFIG,
                    "stored credentials cannot be decrypted; re-enter the password",
                ) from None
        self.check_host(host_of(cfg))
        return cfg

    # -- presentation ---------------------------------------------------------

    @staticmethod
    def public_view(connection: Connection) -> dict[str, Any]:
        cfg = {k: v for k, v in connection.config.items() if k != "password"}
        if connection.secret_encrypted:
            cfg["password"] = REDACTED
        return {
            "id": str(connection.id),
            "workspace_id": str(connection.workspace_id),
            "name": connection.name,
            "kind": connection.kind,
            "config": cfg,
            "created_at": connection.created_at,
            "updated_at": connection.updated_at,
        }
