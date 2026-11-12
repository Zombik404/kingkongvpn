from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.security import totp
from tests.conftest import token_from

PASSWORD = "correct horse battery"


@dataclass
class LoggedIn:
    email: str
    access: str
    refresh: str
    user_id: str

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access}"}


async def register_verified(
    client: AsyncClient, outbox: list[Any], email: str, password: str = PASSWORD
) -> None:
    r = await client.post("/api/v1/auth/register", json={"email": email, "password": password})
    assert r.status_code == 202, r.text
    mail = next(m for m in reversed(outbox) if m.to == email and m.template == "verify_email")
    r = await client.post("/api/v1/auth/verify-email", json={"token": token_from(mail)})
    assert r.status_code == 204, r.text


async def login(client: AsyncClient, email: str, password: str = PASSWORD) -> LoggedIn:
    r = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    body = r.json()
    me = await client.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {body['access_token']}"}
    )
    assert me.status_code == 200, me.text
    return LoggedIn(email, body["access_token"], body["refresh_token"], me.json()["id"])


async def new_user(client: AsyncClient, outbox: list[Any], email: str) -> LoggedIn:
    await register_verified(client, outbox, email)
    return await login(client, email)


async def set_roles(db: AsyncSession, user_id: str, roles: list[str]) -> None:
    await db.execute(update(User).where(User.id == user_id).values(roles=roles))
    await db.commit()


async def enable_mfa(client: AsyncClient, user: LoggedIn) -> bytes:
    """Enable TOTP on the user's current session; returns the raw secret."""
    r = await client.post("/api/v1/auth/mfa/totp/setup", headers=user.headers)
    assert r.status_code == 200, r.text
    import base64

    b32 = r.json()["secret"]
    secret = base64.b32decode(b32 + "=" * (-len(b32) % 8))
    r = await client.post(
        "/api/v1/auth/mfa/totp/enable",
        headers=user.headers,
        json={"code": totp.code_at(secret, totp.current_counter())},
    )
    assert r.status_code == 204, r.text
    return secret


async def staff(
    client: AsyncClient, outbox: list[Any], db: AsyncSession, email: str, roles: list[str]
) -> LoggedIn:
    """A staff user with the given roles on an MFA-verified session."""
    user = await new_user(client, outbox, email)
    await set_roles(db, user.user_id, roles)
    await enable_mfa(client, user)
    return user
