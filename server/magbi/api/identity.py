"""Login and user creation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from magbi.api.deps import ActorDep, ServicesDep, SessionDep
from magbi.api.errors import ApiError
from magbi.auth.tokens import hash_password, issue_token, user_claims, verify_password
from magbi.metadata.models import AuditLog, User, WorkspaceMember

router = APIRouter(tags=["auth"])


class LoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3)
    password: str


class UserIn(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    email: str = Field(min_length=3)
    name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=8)
    platform_admin: bool = Field(default=False, alias="platformAdmin")


def sign_user(svc: ServicesDep, claims: dict[str, object]) -> str:
    cfg = svc.settings
    algorithm = "RS256" if cfg.jwt_private_key_pem else "HS256"
    return issue_token(
        claims,
        secret=cfg.jwt_secret,
        algorithm=algorithm,
        private_key=cfg.jwt_private_key_pem or None,
    )


@router.get("/auth/whoami")
async def whoami(actor: ActorDep) -> dict[str, str | None]:
    return {"kind": actor.kind, "workspaceId": actor.workspace_id, "email": actor.email}


@router.post("/auth/login")
async def login(
    body: LoginIn, request: Request, session: SessionDep, svc: ServicesDep
) -> dict[str, str]:
    email = body.email.strip().lower()
    user = await session.scalar(select(User).where(User.email == email))
    reason = (
        "unknown_email" if user is None
        else "inactive" if not user.is_active
        else "wrong_password" if not verify_password(body.password, user.password_hash)
        else None
    )
    where = {"ip": request.client.host if request.client else None}
    if reason is not None:
        # The caller only ever hears "wrong"; the reason is for administrators.
        session.add(
            AuditLog(
                principal=email,
                action="sign_in_failed",
                object_type="user",
                object_id=str(user.id) if user else None,
                detail={"reason": reason, **where},
            )
        )
        await session.commit()
        raise ApiError(401, "LOGIN_FAILED", "email or password is wrong")
    assert user is not None
    session.add(
        AuditLog(principal=email, action="sign_in", object_type="user", object_id=str(user.id), detail=where)
    )
    rows = await session.scalars(
        select(WorkspaceMember).where(WorkspaceMember.user_id == user.id)
    )
    workspaces = [
        {"id": str(member.workspace_id), "role": member.role.value} for member in rows
    ]
    claims = user_claims(
        str(user.id),
        user.email,
        user.name,
        workspaces,
        ttl_minutes=svc.settings.access_token_ttl_minutes,
        platform_admin=user.is_platform_admin,
    )
    token = sign_user(svc, claims)
    await session.commit()
    return {
        "token": token,
        "expiresAt": (
            datetime.now(UTC) + timedelta(minutes=svc.settings.access_token_ttl_minutes)
        ).isoformat(),
    }


@router.post("/admin/users", status_code=201)
async def create_user(
    body: UserIn, session: SessionDep, actor: ActorDep
) -> dict[str, object]:
    if actor.kind != "dev" and not actor.platform_admin:
        raise ApiError(403, "FORBIDDEN", "a platform admin is required")
    user = User(
        email=body.email.strip().lower(),
        name=body.name.strip(),
        password_hash=hash_password(body.password),
        is_active=True,
        is_platform_admin=body.platform_admin,
    )
    session.add(user)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise ApiError(
            409, "USER_EXISTS", "a user with this email already exists"
        ) from None
    return {
        "id": str(user.id),
        "email": user.email,
        "name": user.name,
        "platformAdmin": user.is_platform_admin,
    }
