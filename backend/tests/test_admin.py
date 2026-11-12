from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models import AuditLog, Plan
from app.security.rbac import ROLE_PERMISSIONS, Perm
from tests.helpers import PASSWORD, login, new_user, set_roles, staff

A = "/api/v1/admin"
ZERO = "00000000-0000-7000-8000-000000000000"

# (method, path, body, permission) — one representative call per permission
ENDPOINTS: list[tuple[str, str, dict[str, Any] | None, Perm]] = [
    ("GET", f"{A}/users", None, Perm.USERS_READ),
    (
        "POST",
        f"{A}/users/{ZERO}/status",
        {"status": "suspended", "reason": "abuse"},
        Perm.USERS_WRITE,
    ),
    ("PUT", f"{A}/users/{ZERO}/roles", {"roles": []}, Perm.ROLES_WRITE),
    (
        "POST",
        f"{A}/users/{ZERO}/subscription/grant",
        {"plan_code": "standard", "days": 3, "reason": "goodwill"},
        Perm.SUBSCRIPTIONS_GRANT,
    ),
    ("GET", f"{A}/plans", None, Perm.PLANS_READ),
    (
        "POST",
        f"{A}/plans",
        {"code": "pro", "names": {"en": "Pro"}, "device_limit": 10},
        Perm.PLANS_WRITE,
    ),
    (
        "POST",
        f"{A}/promo-codes",
        {"code": "NEW10", "kind": "percent_off", "percent_off": 10},
        Perm.PROMO_WRITE,
    ),
    ("GET", f"{A}/settings", None, Perm.SETTINGS_READ),
    ("PUT", f"{A}/settings/trial.days", {"value": 5}, Perm.SETTINGS_WRITE),
    ("GET", f"{A}/audit-logs", None, Perm.AUDIT_READ),
]
ROLES = [None, "support", "ops", "finance", "superadmin"]


@pytest.mark.parametrize("role", ROLES)
async def test_permission_matrix(
    client: AsyncClient, outbox: list[Any], db: Any, role: str | None
) -> None:
    if role is None:
        user = await new_user(client, outbox, "plain@example.com")
    else:
        user = await staff(client, outbox, db, f"{role}@example.com", [role])
    granted = ROLE_PERMISSIONS.get(role, frozenset()) if role else frozenset()
    for method, path, body, perm in ENDPOINTS:
        r = await client.request(method, path, headers=user.headers, json=body)
        if perm in granted:
            assert r.status_code not in (401, 403), (role, path, r.text)
        else:
            assert r.status_code == 403, (role, path, r.status_code)
    # anonymous
    r = await client.get(f"{A}/users")
    assert r.status_code == 401


async def test_staff_without_mfa_session_is_refused(
    client: AsyncClient, outbox: list[Any], db: Any
) -> None:
    user = await new_user(client, outbox, "nomfa@example.com")
    await set_roles(db, user.user_id, ["superadmin"])
    r = await client.get(f"{A}/users", headers=user.headers)
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "mfa_required"


async def test_role_change_signs_staff_out(client: AsyncClient, outbox: list[Any], db: Any) -> None:
    boss = await staff(client, outbox, db, "boss@example.com", ["superadmin"])
    helper = await staff(client, outbox, db, "helper@example.com", ["support"])
    r = await client.put(
        f"{A}/users/{helper.user_id}/roles",
        headers=boss.headers,
        json={"roles": ["support", "finance"]},
    )
    assert r.status_code == 200
    assert r.json()["roles"] == ["finance", "support"]
    assert (await client.get("/api/v1/users/me", headers=helper.headers)).status_code == 401
    r = await client.put(
        f"{A}/users/{boss.user_id}/roles", headers=boss.headers, json={"roles": ["support"]}
    )
    assert r.json()["error"]["code"] == "self_action"
    log = await db.scalar(select(AuditLog).where(AuditLog.action == "admin.roles_changed"))
    assert log.details == {"before": ["support"], "after": ["finance", "support"]}
    assert log.actor_type == "admin"


async def test_suspend_user(client: AsyncClient, outbox: list[Any], db: Any) -> None:
    sup = await staff(client, outbox, db, "sup@example.com", ["support"])
    victim = await new_user(client, outbox, "victim@example.com")
    other_staff = await staff(client, outbox, db, "ops@example.com", ["ops"])
    r = await client.post(
        f"{A}/users/{victim.user_id}/status",
        headers=sup.headers,
        json={"status": "suspended", "reason": "chargeback fraud"},
    )
    assert r.status_code == 200 and r.json()["status"] == "suspended"
    assert (await client.get("/api/v1/users/me", headers=victim.headers)).status_code == 401
    r = await client.post(
        "/api/v1/auth/login", json={"email": "victim@example.com", "password": PASSWORD}
    )
    assert r.json()["error"]["code"] == "account_suspended"
    # support can't suspend staff, nor themselves
    r = await client.post(
        f"{A}/users/{other_staff.user_id}/status",
        headers=sup.headers,
        json={"status": "suspended", "reason": "nope"},
    )
    assert r.status_code == 403
    r = await client.post(
        f"{A}/users/{sup.user_id}/status",
        headers=sup.headers,
        json={"status": "suspended", "reason": "nope"},
    )
    assert r.status_code == 409
    r = await client.post(
        f"{A}/users/{victim.user_id}/status",
        headers=sup.headers,
        json={"status": "active", "reason": "resolved"},
    )
    assert r.json()["status"] == "active"
    await login(client, "victim@example.com")


async def test_search_and_grant(client: AsyncClient, outbox: list[Any], db: Any) -> None:
    sup = await staff(client, outbox, db, "sup2@example.com", ["support"])
    target = await new_user(client, outbox, "customer_1@example.com")
    await new_user(client, outbox, "customerx1@example.com")
    db.add(Plan(code="standard", names={"en": "Standard"}, device_limit=5))
    await db.commit()
    r = await client.get(f"{A}/users", params={"q": "customer_"}, headers=sup.headers)
    assert [u["email"] for u in r.json()] == ["customer_1@example.com"]  # '_' is literal
    r = await client.get(f"{A}/users", params={"q": target.user_id}, headers=sup.headers)
    assert len(r.json()) == 1
    r = await client.post(
        f"{A}/users/{target.user_id}/subscription/grant",
        headers=sup.headers,
        json={"plan_code": "standard", "days": 14, "reason": "outage credit"},
    )
    assert r.status_code == 200 and r.json()["status"] == "active"
    detail = (await client.get(f"{A}/users/{target.user_id}", headers=sup.headers)).json()
    assert detail["subscription"]["plan_code"] == "standard"
    r = await client.post(
        f"{A}/users/{target.user_id}/subscription/revoke",
        headers=sup.headers,
        json={"reason": "granted by mistake"},
    )
    assert r.status_code == 204
    me = (await client.get("/api/v1/subscription", headers=target.headers)).json()
    assert me["entitled"] is False
    r = await client.post(
        f"{A}/users/{target.user_id}/subscription/revoke",
        headers=sup.headers,
        json={"reason": "again"},
    )
    assert r.status_code == 404


async def test_plan_and_price_management(client: AsyncClient, outbox: list[Any], db: Any) -> None:
    fin = await staff(client, outbox, db, "fin@example.com", ["finance"])
    r = await client.post(
        f"{A}/plans",
        headers=fin.headers,
        json={
            "code": "family",
            "names": {"en": "Family", "de": "Familie"},
            "device_limit": 10,
            "features": {"dedicated_ip": False},
        },
    )
    assert r.status_code == 201, r.text
    plan_id = r.json()["id"]
    r = await client.post(
        f"{A}/plans",
        headers=fin.headers,
        json={"code": "family", "names": {"en": "Dup"}, "device_limit": 1},
    )
    assert r.status_code == 409
    r = await client.post(
        f"{A}/plans",
        headers=fin.headers,
        json={"code": "nolang", "names": {"de": "X"}, "device_limit": 1},
    )
    assert r.status_code == 422
    r = await client.post(
        f"{A}/plans/{plan_id}/prices",
        headers=fin.headers,
        json={
            "period_unit": "month",
            "currency": "EUR",
            "amount_minor": 999,
            "provider_ids": {"stripe_price_id": "price_test_123"},
        },
    )
    assert r.status_code == 201, r.text
    price_id = r.json()["id"]
    r = await client.post(
        f"{A}/plans/{plan_id}/prices",
        headers=fin.headers,
        json={"period_unit": "week", "currency": "EUR", "amount_minor": 1},
    )
    assert r.status_code == 422
    plans = (await client.get("/api/v1/plans")).json()
    assert [p["code"] for p in plans] == ["family"]
    r = await client.patch(f"{A}/prices/{price_id}", headers=fin.headers, json={"active": False})
    assert r.json()["active"] is False
    assert (await client.get("/api/v1/plans")).json() == []
    r = await client.patch(
        f"{A}/plans/{plan_id}", headers=fin.headers, json={"device_limit": 8, "active": False}
    )
    assert r.json()["device_limit"] == 8
    prices = (await client.get(f"{A}/plans/{plan_id}/prices", headers=fin.headers)).json()
    assert len(prices) == 1


async def test_settings_validation_and_audit(
    client: AsyncClient, outbox: list[Any], db: Any
) -> None:
    ops = await staff(client, outbox, db, "ops2@example.com", ["ops"])
    r = await client.put(f"{A}/settings/trial.days", headers=ops.headers, json={"value": 99})
    assert r.status_code == 422
    r = await client.put(f"{A}/settings/trial.days", headers=ops.headers, json={"value": "5"})
    assert r.status_code == 422  # strict: no string coercion
    r = await client.put(f"{A}/settings/nope", headers=ops.headers, json={"value": 1})
    assert r.status_code == 404
    r = await client.put(f"{A}/settings/trial.days", headers=ops.headers, json={"value": 7})
    assert r.json() == {"key": "trial.days", "value": 7}
    all_settings = (await client.get(f"{A}/settings", headers=ops.headers)).json()
    assert all_settings["trial.days"]["value"] == 7
    assert all_settings["trial.days"]["default"] == 3
    logs = (
        await client.get(f"{A}/audit-logs", params={"action": "admin"}, headers=ops.headers)
    ).json()
    assert logs[0]["action"] == "admin.setting_changed"
    assert logs[0]["details"] == {"before": 3, "after": 7}


async def test_promo_admin(client: AsyncClient, outbox: list[Any], db: Any) -> None:
    fin = await staff(client, outbox, db, "fin2@example.com", ["finance"])
    r = await client.post(
        f"{A}/promo-codes",
        headers=fin.headers,
        json={"code": "X1", "kind": "amount_off", "amount_off_minor": 100},
    )
    assert r.status_code == 422  # currency required
    r = await client.post(
        f"{A}/promo-codes",
        headers=fin.headers,
        json={"code": "FREE7", "kind": "free_days", "free_days": 7, "plan_code": "missing"},
    )
    assert r.status_code == 404
    r = await client.post(
        f"{A}/promo-codes",
        headers=fin.headers,
        json={"code": "SAVE10", "kind": "percent_off", "percent_off": 10, "max_redemptions": 100},
    )
    assert r.status_code == 201
    pid = r.json()["id"]
    r = await client.post(
        f"{A}/promo-codes",
        headers=fin.headers,
        json={"code": "save10", "kind": "percent_off", "percent_off": 5},
    )
    assert r.status_code == 409  # case-insensitive uniqueness
    r = await client.patch(f"{A}/promo-codes/{pid}", headers=fin.headers, json={"active": False})
    assert r.json()["active"] is False
    listing = (await client.get(f"{A}/promo-codes", headers=fin.headers)).json()
    assert len(listing) == 1
