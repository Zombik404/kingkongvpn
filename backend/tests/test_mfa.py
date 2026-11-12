from __future__ import annotations

from typing import Any

from httpx import AsyncClient
from sqlalchemy import select

from app.core.context import AppContext
from app.models import User
from app.security import totp
from tests.helpers import PASSWORD, enable_mfa, new_user

API = "/api/v1/auth"


async def test_totp_secret_is_encrypted_at_rest(
    client: AsyncClient, outbox: list[Any], db: Any, ctx: AppContext
) -> None:
    user = await new_user(client, outbox, "mfa1@example.com")
    secret = await enable_mfa(client, user)
    row = await db.scalar(select(User).where(User.email == "mfa1@example.com"))
    assert row.totp_enabled_at is not None
    assert secret not in row.totp_secret_encrypted
    assert ctx.cipher.decrypt(row.totp_secret_encrypted, context=b"totp:" + row.id.bytes) == secret
    # ciphertext is bound to the user: another user's context can't decrypt it
    other_context = b"totp:" + bytes(16)
    try:
        ctx.cipher.decrypt(row.totp_secret_encrypted, context=other_context)
    except Exception:
        pass
    else:
        raise AssertionError("decrypt with wrong context must fail")
    me = (await client.get("/api/v1/users/me", headers=user.headers)).json()
    assert me["mfa_enabled"] is True


async def test_login_with_mfa_challenge_and_replay(client: AsyncClient, outbox: list[Any]) -> None:
    user = await new_user(client, outbox, "mfa2@example.com")
    secret = await enable_mfa(client, user)
    r = await client.post(f"{API}/login", json={"email": "mfa2@example.com", "password": PASSWORD})
    assert r.status_code == 200
    body = r.json()
    assert body["mfa_required"] is True
    assert "access_token" not in body
    challenge = body["mfa_token"]
    bad = await client.post(f"{API}/mfa/verify", json={"mfa_token": challenge, "code": "000000"})
    assert bad.status_code == 401
    # enable_mfa consumed the current step; the next one is within the allowed window
    code = totp.code_at(secret, totp.current_counter() + 1)
    ok = await client.post(f"{API}/mfa/verify", json={"mfa_token": challenge, "code": code})
    assert ok.status_code == 200, ok.text
    replay = await client.post(f"{API}/mfa/verify", json={"mfa_token": challenge, "code": code})
    assert replay.status_code == 401
    assert replay.json()["error"]["code"] == "invalid_mfa_code"
    # Using the challenge as an access token doesn't work
    r = await client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {challenge}"})
    assert r.status_code == 401


async def test_setup_twice_and_disable(client: AsyncClient, outbox: list[Any]) -> None:
    user = await new_user(client, outbox, "mfa3@example.com")
    r = await client.post(f"{API}/mfa/totp/enable", headers=user.headers, json={"code": "123456"})
    assert r.json()["error"]["code"] == "mfa_setup_required"
    secret = await enable_mfa(client, user)
    r = await client.post(f"{API}/mfa/totp/setup", headers=user.headers)
    assert r.status_code == 409
    code = totp.code_at(secret, totp.current_counter() + 1)
    r = await client.post(
        f"{API}/mfa/totp/disable",
        headers=user.headers,
        json={"password": "wrong-password", "code": code},
    )
    assert r.status_code == 401
    r = await client.post(
        f"{API}/mfa/totp/disable", headers=user.headers, json={"password": PASSWORD, "code": code}
    )
    assert r.status_code == 204
    r = await client.post(f"{API}/login", json={"email": "mfa3@example.com", "password": PASSWORD})
    assert "access_token" in r.json()
    r = await client.post(
        f"{API}/mfa/totp/disable", headers=user.headers, json={"password": PASSWORD, "code": code}
    )
    assert r.json()["error"]["code"] == "mfa_not_enabled"


def test_totp_rfc6238_vectors() -> None:
    # RFC 6238 Appendix B (SHA-1), truncated to 6 digits
    secret = b"12345678901234567890"
    vectors = {
        59: "287082",
        1111111109: "081804",
        1111111111: "050471",
        1234567890: "005924",
        2000000000: "279037",
        20000000000: "353130",
    }
    for t, expected in vectors.items():
        assert totp.code_at(secret, t // 30) == expected
        assert totp.verify(secret, expected, now=t) == t // 30
    assert totp.verify(secret, "287082", now=59 + 30) is not None  # previous step allowed
    assert totp.verify(secret, "287082", now=59 + 61) is None  # too old
    assert totp.verify(secret, "28708x", now=59) is None
    assert totp.verify(secret, "287082", now=59, last_counter=1) is None
    uri = totp.provisioning_uri(secret, account="a@b.c", issuer="Global VPN")
    assert uri.startswith("otpauth://totp/Global%20VPN%3Aa%40b.c?secret=")
