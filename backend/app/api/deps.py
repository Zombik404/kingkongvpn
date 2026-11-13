"""FastAPI dependencies: DB session, app context, authenticated principal, RBAC."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Coroutine
from typing import Annotated, Any

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import AppContext
from app.core.errors import AppError, NotAuthenticated, PermissionDenied
from app.models import AuthSession, User
from app.models.base import utcnow
from app.security.principal import ClientInfo, Principal
from app.security.rbac import Perm, permissions_for

_bearer = HTTPBearer(auto_error=False, description="Access token from /api/v1/auth/login")


def get_ctx(request: Request) -> AppContext:
    ctx: AppContext = request.app.state.ctx
    return ctx


Ctx = Annotated[AppContext, Depends(get_ctx)]


async def get_db(ctx: Ctx) -> AsyncIterator[AsyncSession]:
    async with ctx.sessionmaker() as session:
        try:
            yield session
        except BaseException:
            await session.rollback()
            raise


Db = Annotated[AsyncSession, Depends(get_db)]


def get_client(request: Request) -> ClientInfo:
    # `request.client` already reflects X-Forwarded-For when uvicorn runs with
    # --proxy-headers behind our Nginx (see Dockerfile CMD).
    ip = request.client.host if request.client else None
    return ClientInfo(ip=ip, user_agent=request.headers.get("user-agent"))


Client = Annotated[ClientInfo, Depends(get_client)]


async def principal_from_token(ctx: AppContext, db: AsyncSession, token: str) -> Principal:
    """Validate an access token against the live user and session (also used by WebSockets)."""
    claims = ctx.tokens.decode_access(token)
    row = (
        await db.execute(
            select(User, AuthSession)
            .join(AuthSession, AuthSession.user_id == User.id)
            .where(User.id == claims.sub, AuthSession.id == claims.sid)
        )
    ).one_or_none()
    if row is None:
        raise NotAuthenticated("Invalid or expired token.", headers={"WWW-Authenticate": "Bearer"})
    user, session = row
    if (
        not user.is_active
        or user.token_version != claims.ver
        or session.revoked_at is not None
        or session.expires_at <= utcnow()
    ):
        raise NotAuthenticated("Invalid or expired token.", headers={"WWW-Authenticate": "Bearer"})
    return Principal(user=user, session=session, claims=claims)


async def get_principal(
    ctx: Ctx,
    db: Db,
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Principal:
    if creds is None or creds.scheme.lower() != "bearer":
        raise NotAuthenticated(headers={"WWW-Authenticate": "Bearer"})
    return await principal_from_token(ctx, db, creds.credentials)


CurrentPrincipal = Annotated[Principal, Depends(get_principal)]


class MfaRequiredForAdmin(AppError):
    status_code = 403
    code = "mfa_required"
    message = "Staff actions require two-factor authentication on this session."


def require(perm: Perm) -> Callable[..., Coroutine[Any, Any, Principal]]:
    """Route dependency: caller must hold `perm` via a staff role (and MFA if required).

    Roles are read from the database row (not the token), so a role removal takes
    effect on the next request.
    """

    async def dependency(principal: CurrentPrincipal, ctx: Ctx) -> Principal:
        if perm not in permissions_for(principal.user.roles):
            raise PermissionDenied()
        if ctx.settings.admin_require_mfa and not principal.session.mfa_verified:
            raise MfaRequiredForAdmin()
        return principal

    return dependency
