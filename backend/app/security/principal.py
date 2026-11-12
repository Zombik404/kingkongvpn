from __future__ import annotations

from dataclasses import dataclass

from app.models import AuthSession, User
from app.security.tokens import AccessClaims


@dataclass(frozen=True)
class Principal:
    """The authenticated caller: user + live session, both re-checked against the DB."""

    user: User
    session: AuthSession
    claims: AccessClaims


@dataclass(frozen=True)
class ClientInfo:
    ip: str | None
    user_agent: str | None
