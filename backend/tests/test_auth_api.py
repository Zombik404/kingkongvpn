from __future__ import annotations

import datetime as dt
from typing import Any

import jwt
from httpx import AsyncClient
from sqlalchemy import select, update

from app.core.context import AppContext
from app.models import AuditLog, AuthSession, User, UserActionToken
from tests.conftest import token_from
from tests.helpers import PASSWORD, login, new_user, register_verified

API = "/api/v1/auth"


async def test_register_sends_verification_and_hashes_password(
    client: AsyncClient, outbox: list[Any], db: Any
) -> None:
    r = await client.post(
        f"{API}/register",
        json={"email": "Ann@Example.com", "password": PASSWORD},
        headers={"Accept-Language": "ru-RU,ru;q=0.9,en;q=0.5"},
    )
    assert r.status_code == 202
    assert r.json()["status"] == "accepted"
    [mail] = outbox
    assert mail.to == "ann@example.com"
    assert mail.template == "verify_email"
    assert "Подтвердите" in mail.subject  # Russian from Accept-Language
    assert mail.action_url.startswith("https://web.test/verify-email?token=")
    user = await db.scalar(select(User).where(User.email == "ann@example.com"))
    assert user.locale == "ru"
    assert user.password_hash.startswith("$argon2id$")
    assert PASSWORD not in user.password_hash
    token = await db.scalar(select(UserActionToken))
    assert token_from(mail).encode() != token.token_hash  # stored hashed


async def test_register_existing_email_is_indistinguishable(
    client: AsyncClient, outbox: list[Any]
) -> None:
    await register_verified(client, outbox, "bob@example.com")
    outbox.clear()
    r = await client.post(
        f"{API}/register", json={"email": "BOB@example.com", "password": PASSWORD}
    )
    assert r.status_code == 202
    assert r.json()["detail"]
    [mail] = outbox
    assert mail.template == "account_exists"  # owner is told; caller learns nothing


async def test_register_rejects_weak_password(client: AsyncClient) -> None:
    r = await client.post(f"{API}/register", json={"email": "c@example.com", "password": "short"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "weak_password"
    r = await client.post(f"{API}/register", json={"email": "c@example.com", "password": "a" * 12})
    assert r.json()["error"]["code"] == "weak_password"


async def test_unverified_user_cannot_login(client: AsyncClient, outbox: list[Any]) -> None:
    await client.post(f"{API}/register", json={"email": "d@example.com", "password": PASSWORD})
    r = await client.post(f"{API}/login", json={"email": "d@example.com", "password": PASSWORD})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "email_not_verified"


async def test_verification_token_single_use_and_resend(
    client: AsyncClient, outbox: list[Any]
) -> None:
    await client.post(f"{API}/register", json={"email": "e@example.com", "password": PASSWORD})
    first = token_from(outbox[-1])
    r = await client.post(f"{API}/resend-verification", json={"email": "e@example.com"})
    assert r.status_code == 202
    second = token_from(outbox[-1])
    assert first != second
    r = await client.post(f"{API}/verify-email", json={"token": first})
    assert r.status_code == 400  # superseded by the resend
    assert (await client.post(f"{API}/verify-email", json={"token": second})).status_code == 204
    assert (await client.post(f"{API}/verify-email", json={"token": second})).status_code == 400
    # resend for verified or unknown addresses: same answer, no mail
    n = len(outbox)
    for email in ("e@example.com", "nobody@example.com"):
        r = await client.post(f"{API}/resend-verification", json={"email": email})
        assert r.status_code == 202
    assert len(outbox) == n


async def test_expired_verification_token(client: AsyncClient, outbox: list[Any], db: Any) -> None:
    await client.post(f"{API}/register", json={"email": "f@example.com", "password": PASSWORD})
    await db.execute(
        update(UserActionToken).values(expires_at=dt.datetime.now(dt.UTC) - dt.timedelta(seconds=1))
    )
    await db.commit()
    r = await client.post(f"{API}/verify-email", json={"token": token_from(outbox[-1])})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "invalid_token"


async def test_login_wrong_password_and_unknown_email_look_the_same(
    client: AsyncClient, outbox: list[Any], db: Any
) -> None:
    await register_verified(client, outbox, "g@example.com")
    a = await client.post(
        f"{API}/login", json={"email": "g@example.com", "password": "wrong-pass-1"}
    )
    b = await client.post(
        f"{API}/login", json={"email": "x@example.com", "password": "wrong-pass-1"}
    )
    assert a.status_code == b.status_code == 401
    assert a.json() == b.json()
    failures = (
        await db.scalars(
            select(AuditLog).where(AuditLog.action == "auth.login", AuditLog.result == "failure")
        )
    ).all()
    assert len(failures) == 2
    assert all(f.ip_prefix == "203.0.113.0/24" for f in failures)
    assert all("password" not in str(f.details) for f in failures)


async def test_login_success_and_me(client: AsyncClient, outbox: list[Any]) -> None:
    user = await new_user(client, outbox, "h@example.com")
    r = await client.get("/api/v1/users/me", headers=user.headers)
    assert r.json()["email"] == "h@example.com"
    assert r.json()["email_verified"] is True
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["x-content-type-options"] == "nosniff"


async def test_access_token_validation(
    client: AsyncClient, outbox: list[Any], ctx: AppContext
) -> None:
    user = await new_user(client, outbox, "i@example.com")
    assert (await client.get("/api/v1/users/me")).status_code == 401
    bad = {"Authorization": "Bearer not-a-jwt"}
    assert (await client.get("/api/v1/users/me", headers=bad)).status_code == 401
    # Wrong algorithm / forged signature
    claims = jwt.decode(user.access, options={"verify_signature": False})
    forged = jwt.encode(claims, "s" * 64, algorithm="HS256")
    r = await client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {forged}"})
    assert r.status_code == 401
    # An MFA challenge token is not an access token
    mfa = ctx.tokens.issue_mfa_challenge(user_id=claims["sub"], ver=0)
    r = await client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {mfa}"})
    assert r.status_code == 401


async def test_refresh_rotates_and_reuse_revokes_family(
    client: AsyncClient, outbox: list[Any], db: Any
) -> None:
    user = await new_user(client, outbox, "j@example.com")
    r1 = await client.post(f"{API}/refresh", json={"refresh_token": user.refresh})
    assert r1.status_code == 200
    new = r1.json()
    assert new["refresh_token"] != user.refresh
    assert new["session_id"]
    # Replay of the rotated token → theft assumed → whole session revoked
    r2 = await client.post(f"{API}/refresh", json={"refresh_token": user.refresh})
    assert r2.status_code == 401
    r3 = await client.post(f"{API}/refresh", json={"refresh_token": new["refresh_token"]})
    assert r3.status_code == 401
    r4 = await client.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {new['access_token']}"}
    )
    assert r4.status_code == 401
    sess = await db.scalar(select(AuthSession))
    assert sess.revoke_reason == "refresh_reuse"
    assert (
        await db.scalar(select(AuditLog.id).where(AuditLog.action == "auth.refresh_reuse_detected"))
        is not None
    )


async def test_refresh_unknown_and_expired(client: AsyncClient, outbox: list[Any], db: Any) -> None:
    r = await client.post(f"{API}/refresh", json={"refresh_token": "x" * 43})
    assert r.status_code == 401
    user = await new_user(client, outbox, "k@example.com")
    await db.execute(
        update(AuthSession).values(expires_at=dt.datetime.now(dt.UTC) - dt.timedelta(seconds=1))
    )
    await db.commit()
    r = await client.post(f"{API}/refresh", json={"refresh_token": user.refresh})
    assert r.status_code == 401
    assert (await client.get("/api/v1/users/me", headers=user.headers)).status_code == 401


async def test_logout_and_logout_all(client: AsyncClient, outbox: list[Any]) -> None:
    await register_verified(client, outbox, "l@example.com")
    a = await login(client, "l@example.com")
    b = await login(client, "l@example.com")
    sessions = await client.get("/api/v1/users/me/sessions", headers=a.headers)
    assert len(sessions.json()) == 2
    assert sum(s["current"] for s in sessions.json()) == 1
    assert (await client.post(f"{API}/logout", headers=a.headers)).status_code == 204
    assert (await client.get("/api/v1/users/me", headers=a.headers)).status_code == 401
    assert (
        await client.post(f"{API}/refresh", json={"refresh_token": a.refresh})
    ).status_code == 401
    assert (await client.get("/api/v1/users/me", headers=b.headers)).status_code == 200
    c = await login(client, "l@example.com")
    assert (await client.post(f"{API}/logout-all", headers=c.headers)).status_code == 204
    for s in (b, c):
        assert (await client.get("/api/v1/users/me", headers=s.headers)).status_code == 401


async def test_revoke_other_session(client: AsyncClient, outbox: list[Any]) -> None:
    await register_verified(client, outbox, "l2@example.com")
    a = await login(client, "l2@example.com")
    b = await login(client, "l2@example.com")
    sessions = (await client.get("/api/v1/users/me/sessions", headers=a.headers)).json()
    other = next(s["id"] for s in sessions if not s["current"])
    r = await client.delete(f"/api/v1/users/me/sessions/{other}", headers=a.headers)
    assert r.status_code == 204
    assert (await client.get("/api/v1/users/me", headers=b.headers)).status_code == 401
    r = await client.delete(f"/api/v1/users/me/sessions/{other}", headers=a.headers)
    assert r.status_code == 404


async def test_password_reset_flow(client: AsyncClient, outbox: list[Any]) -> None:
    await register_verified(client, outbox, "m@example.com")
    old = await login(client, "m@example.com")
    outbox.clear()
    for email in ("m@example.com", "unknown@example.com"):
        r = await client.post(f"{API}/password-reset/request", json={"email": email})
        assert r.status_code == 202
    [mail] = outbox
    assert mail.template == "password_reset"
    token = token_from(mail)
    r = await client.post(
        f"{API}/password-reset/confirm", json={"token": token, "new_password": "short"}
    )
    assert r.status_code == 422
    r = await client.post(
        f"{API}/password-reset/confirm",
        json={"token": token, "new_password": "a brand new passphrase"},
    )
    assert r.status_code == 204  # policy failure rolled back; the token was still usable
    assert outbox[-1].template == "password_changed"
    assert (await client.get("/api/v1/users/me", headers=old.headers)).status_code == 401
    r = await client.post(
        f"{API}/password-reset/confirm",
        json={"token": token, "new_password": "another new passphrase"},
    )
    assert r.status_code == 400  # single use
    r = await client.post(f"{API}/login", json={"email": "m@example.com", "password": PASSWORD})
    assert r.status_code == 401
    await login(client, "m@example.com", "a brand new passphrase")


async def test_change_password_keeps_current_session(
    client: AsyncClient, outbox: list[Any]
) -> None:
    await register_verified(client, outbox, "n@example.com")
    a = await login(client, "n@example.com")
    b = await login(client, "n@example.com")
    r = await client.post(
        f"{API}/password/change",
        headers=a.headers,
        json={"current_password": "wrong-one-here", "new_password": "x" * 12},
    )
    assert r.status_code == 401
    r = await client.post(
        f"{API}/password/change",
        headers=a.headers,
        json={"current_password": PASSWORD, "new_password": "fresh passphrase 2"},
    )
    assert r.status_code == 204
    assert (await client.get("/api/v1/users/me", headers=a.headers)).status_code == 200
    assert (await client.get("/api/v1/users/me", headers=b.headers)).status_code == 401


async def test_login_rate_limit_per_account(client: AsyncClient, outbox: list[Any]) -> None:
    await register_verified(client, outbox, "o@example.com")
    codes = []
    for _ in range(11):
        r = await client.post(
            f"{API}/login", json={"email": "o@example.com", "password": "wrong-pass-1"}
        )
        codes.append(r.status_code)
    assert codes[:10] == [401] * 10
    assert codes[10] == 429
    assert int(r.headers["retry-after"]) > 0
    # even the right password is refused while limited
    r = await client.post(f"{API}/login", json={"email": "o@example.com", "password": PASSWORD})
    assert r.status_code == 429


async def test_suspended_user_cannot_login(client: AsyncClient, outbox: list[Any], db: Any) -> None:
    user = await new_user(client, outbox, "p@example.com")
    await db.execute(update(User).values(status="suspended"))
    await db.commit()
    assert (await client.get("/api/v1/users/me", headers=user.headers)).status_code == 401
    r = await client.post(f"{API}/login", json={"email": "p@example.com", "password": PASSWORD})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "account_suspended"
