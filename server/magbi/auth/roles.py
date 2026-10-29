"""Workspace permission checks.

``admin`` outranks ``editor``, which outranks ``viewer``. A dev bypass and a
platform admin pass every workspace check. Embed and service callers do not.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ActorKind = Literal["user", "embed", "service", "dev"]
_RANK = {"viewer": 1, "editor": 2, "admin": 3}


@dataclass(frozen=True, slots=True)
class Actor:
    kind: ActorKind
    subject: str
    email: str
    name: str
    platform_admin: bool = False
    memberships: tuple[tuple[str, str], ...] = ()
    workspace_id: str | None = None
    datasets: tuple[str, ...] = ()
    reports: tuple[str, ...] = ()
    rls_roles: tuple[str, ...] = ()


def permits(actor: Actor, workspace_id: str, minimum: str) -> bool:
    """Whether ``actor`` may take an action that needs ``minimum`` in the workspace."""
    if actor.kind == "dev" or actor.platform_admin:
        return True
    if actor.kind != "user":
        return False
    role = next((item for wid, item in actor.memberships if wid == workspace_id), None)
    if role is None:
        return False
    return _RANK.get(role, 0) >= _RANK[minimum]


def permits_service(actor: Actor, workspace_id: str) -> bool:
    """A service token may mint embed tokens and refresh its own workspace."""
    if actor.kind == "dev":
        return True
    return actor.kind == "service" and actor.workspace_id == workspace_id
