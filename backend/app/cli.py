"""Operator commands: `python -m app.cli <command>`.

create-staff EMAIL ROLE                  admin-panel account with a one-time password (no email)
grant-role EMAIL ROLE                    give a staff role (bootstraps the first superadmin)
seed-dev                                 dev-only sample plans/prices/settings
set-price PLAN UNIT COUNT CURRENCY AMT   e.g. set-price standard month 3 USD 12.99
cryptobot-check                          verify the @CryptoBot token, list asset codes
bootstrap-catalog                        create plans + launch prices (idempotent, any env)
node-register --hostname --country ...   register a VPN node, print its id + API token
create-invites --count 10 --days 30      single-use invite codes for the closed test
set-setting KEY JSON                     e.g. set-setting access.invite_only true
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from decimal import Decimal, InvalidOperation

from sqlalchemy import select, update

from app.core.config import get_settings
from app.core.context import AppContext
from app.models import Plan, PlanPrice, User
from app.models.enums import ActorType, Role
from app.payments.cryptobot import CryptoBotClient
from app.services import audit
from app.services import settings as settings_service


async def grant_role(email: str, role: str) -> int:
    ctx = AppContext.create(get_settings(), null_pool=True)
    try:
        async with ctx.sessionmaker() as db:
            user = await db.scalar(
                select(User).where(User.email == email.lower()).with_for_update()
            )
            if user is None or not user.is_active or user.email_verified_at is None:
                print("no active, verified user with that email", file=sys.stderr)
                return 1
            if role not in user.roles:
                user.roles = sorted({*(user.roles or []), role})
                user.token_version += 1
            audit.record(
                db,
                action="cli.role_granted",
                actor_type=ActorType.SYSTEM,
                target_type="user",
                target_id=user.id,
                details={"role": role},
            )
            await db.commit()
            print(f"{email}: roles = {', '.join(user.roles)} (sign in again and enable 2FA)")
            return 0
    finally:
        await ctx.close()


async def create_staff(email: str, role: str) -> int:
    """Create (or reset) a staff account for the admin panel without email delivery.

    Prints a strong one-time password; the person signs in at /admin/, must set up 2FA
    (TOTP) right away, and should change the password afterwards. Re-running for an existing
    account sets a new password and signs it out everywhere."""
    import secrets

    from app.models.base import utcnow
    from app.models.enums import UserStatus

    if role not in {r.value for r in Role}:
        print(f"unknown role {role!r}; one of: {', '.join(r.value for r in Role)}", file=sys.stderr)
        return 1
    from pydantic import EmailStr, TypeAdapter, ValidationError

    try:  # the same check the login form applies, so the account can actually sign in
        email = TypeAdapter(EmailStr).validate_python(email.strip()).lower()
    except ValidationError:
        print("give a valid email address (the login form must accept it)", file=sys.stderr)
        return 1
    password = secrets.token_urlsafe(18)
    ctx = AppContext.create(get_settings(), null_pool=True)
    try:
        async with ctx.sessionmaker() as db:
            user = await db.scalar(select(User).where(User.email == email).with_for_update())
            if user is None:
                user = User(email=email, email_verified_at=utcnow(), locale="ru", roles=[])
                db.add(user)
            elif user.status != UserStatus.ACTIVE:
                print("that account is suspended or deleted", file=sys.stderr)
                return 1
            if user.telegram_id is not None:
                print("that account is a Telegram user account; use another email", file=sys.stderr)
                return 1
            user.email_verified_at = user.email_verified_at or utcnow()
            user.password_hash = await ctx.passwords.hash(password)
            user.roles = sorted({*(user.roles or []), role})
            user.token_version = (user.token_version or 0) + 1
            await db.flush()
            audit.record(
                db,
                action="cli.staff_created",
                actor_type=ActorType.SYSTEM,
                target_type="user",
                target_id=user.id,
                details={"role": role},
            )
            await db.commit()
            print(f"{email}: roles = {', '.join(user.roles)}")
            print(f"one-time password: {password}")
            print("sign in at https://<your domain>/admin/ and set up two-factor authentication")
            return 0
    finally:
        await ctx.close()


async def seed_dev() -> int:
    settings = get_settings()
    if settings.app_env != "development":
        print("seed-dev only runs with APP_ENV=development", file=sys.stderr)
        return 1
    ctx = AppContext.create(settings, null_pool=True)
    try:
        async with ctx.sessionmaker() as db:
            if await db.scalar(select(Plan.id).limit(1)) is not None:
                print("plans already exist; nothing to do")
                return 0
            db.add_all(
                [
                    Plan(
                        code="trial",
                        names={"en": "Trial", "ru": "Пробный"},
                        device_limit=2,
                        is_trial=True,
                        sort_order=0,
                    ),
                    Plan(
                        code="standard",
                        names={"en": "Standard", "ru": "Стандарт"},
                        device_limit=5,
                        sort_order=10,
                    ),
                ]
            )
            await settings_service.set_value(db, "trial.enabled", True, actor_id=None)
            await db.commit()
        for months, amount in LAUNCH_PRICES_USD:
            await set_price("standard", "month", months, "USD", amount, quiet=True)
        print("seeded dev plans: trial, standard (1/3/6/12 months, launch USD prices)")
        return 0
    finally:
        await ctx.close()


async def set_price(
    plan_code: str, unit: str, count: int, currency: str, amount: str, *, quiet: bool = False
) -> int:
    """Create the price and deactivate the previous active one for the same period/currency.

    Old rows are kept (payments reference them), never edited."""
    try:
        minor = int((Decimal(amount) * 100).to_integral_value())
    except InvalidOperation:
        print("amount must be a number like 4.99", file=sys.stderr)
        return 1
    if minor <= 0 or Decimal(amount) * 100 != minor:
        print("amount must be positive with at most 2 decimals", file=sys.stderr)
        return 1
    ctx = AppContext.create(get_settings(), null_pool=True)
    try:
        async with ctx.sessionmaker() as db:
            plan = await db.scalar(select(Plan).where(Plan.code == plan_code))
            if plan is None:
                print(f"no plan {plan_code!r}", file=sys.stderr)
                return 1
            await db.execute(
                update(PlanPrice)
                .where(
                    PlanPrice.plan_id == plan.id,
                    PlanPrice.period_unit == unit,
                    PlanPrice.period_count == count,
                    PlanPrice.currency == currency,
                    PlanPrice.active.is_(True),
                )
                .values(active=False)
            )
            price = PlanPrice(
                plan_id=plan.id,
                period_unit=unit,
                period_count=count,
                currency=currency,
                amount_minor=minor,
            )
            db.add(price)
            await db.flush()
            audit.record(
                db,
                action="cli.price_set",
                actor_type=ActorType.SYSTEM,
                target_type="plan_price",
                target_id=price.id,
                details={
                    "plan": plan_code,
                    "unit": unit,
                    "count": count,
                    "currency": currency,
                    "amount_minor": minor,
                },
            )
            await db.commit()
            if not quiet:
                print(f"{plan_code}: {count} {unit} = {amount} {currency} (id {price.id})")
            return 0
    finally:
        await ctx.close()


async def cryptobot_check() -> int:
    """Verify the token and show which asset codes the API offers (e.g. TON vs GRAM)."""
    settings = get_settings()
    if not settings.cryptobot_enabled:
        print("CRYPTOBOT_API_TOKEN is not set", file=sys.stderr)
        return 1
    client = CryptoBotClient(settings)
    try:
        me = await client.get_me()
        currencies = await client.get_currencies()
    finally:
        await client.aclose()
    print(f"network: {settings.cryptobot_network}  app: {me.get('name')} (id {me.get('app_id')})")
    crypto = sorted(
        {str(c.get("code")) for c in currencies if c.get("is_blockchain") or c.get("is_stablecoin")}
    )
    fiat = sorted({str(c.get("code")) for c in currencies if c.get("is_fiat")})
    print("crypto assets:", ", ".join(crypto) or "?")
    print("fiat:", ", ".join(fiat) or "?")
    print("configured CRYPTOBOT_ACCEPTED_ASSETS:", ", ".join(settings.cryptobot_accepted_assets))
    client = CryptoBotClient(settings)
    try:
        resolved = await client.accepted_assets()
    except Exception as exc:
        print(f"ERROR: none of the configured assets is offered: {exc}", file=sys.stderr)
        return 2
    finally:
        await client.aclose()
    print("invoices will accept:", ", ".join(resolved))
    return 0


# Launch catalogue agreed with the owner (2026-11-13): USD, 1/3/6/12 months.
LAUNCH_PRICES_USD = ((1, "5.00"), (3, "13.00"), (6, "24.00"), (12, "42.00"))


async def bootstrap_catalog() -> int:
    """Idempotent, safe in any environment: create the `trial` and `standard` plans if missing
    and set the launch prices where the active price differs."""
    ctx = AppContext.create(get_settings(), null_pool=True)
    try:
        async with ctx.sessionmaker() as db:
            existing = {p.code for p in (await db.scalars(select(Plan))).all()}
            if "trial" not in existing:
                db.add(
                    Plan(
                        code="trial",
                        names={"en": "Trial", "ru": "Пробный"},
                        device_limit=2,
                        is_trial=True,
                        sort_order=0,
                    )
                )
            if "standard" not in existing:
                db.add(
                    Plan(
                        code="standard",
                        names={"en": "Standard", "ru": "Стандарт"},
                        device_limit=5,
                        sort_order=10,
                    )
                )
            await db.commit()
            plan = await db.scalar(select(Plan).where(Plan.code == "standard"))
            assert plan is not None
            active = {
                (p.period_count, p.amount_minor)
                for p in (
                    await db.scalars(
                        select(PlanPrice).where(
                            PlanPrice.plan_id == plan.id,
                            PlanPrice.period_unit == "month",
                            PlanPrice.currency == "USD",
                            PlanPrice.active.is_(True),
                        )
                    )
                ).all()
            }
    finally:
        await ctx.close()
    for months, amount in LAUNCH_PRICES_USD:
        if (months, int(Decimal(amount) * 100)) not in active:
            await set_price("standard", "month", months, "USD", amount, quiet=True)
    print("catalogue ready: standard = " + ", ".join(f"{m} mo ${a}" for m, a in LAUNCH_PRICES_USD))
    return 0


async def node_register(
    hostname: str,
    country: str,
    city: str | None,
    ipv4: str | None,
    ipv6: str | None,
    port: int,
    wg_public_key: str,
    max_peers: int,
) -> int:
    """Register (or re-register) a VPN node; prints JSON with its id and a fresh API token.

    The token is shown once and stored only as an HMAC. Re-running rotates it."""
    import ipaddress
    import json

    from app.models import Location, Server
    from app.schemas.domain import _wg_public_key
    from app.vpn.service import new_node_token

    try:
        _wg_public_key(wg_public_key)
        v4 = ipaddress.IPv4Address(ipv4) if ipv4 else None
        v6 = ipaddress.IPv6Address(ipv6) if ipv6 else None
    except ValueError as exc:
        print(f"invalid argument: {exc}", file=sys.stderr)
        return 1
    if v4 is None and v6 is None:
        print("need --ipv4 and/or --ipv6", file=sys.stderr)
        return 1
    country = country.upper()
    ctx = AppContext.create(get_settings(), null_pool=True)
    try:
        async with ctx.sessionmaker() as db:
            loc = await db.scalar(
                select(Location).where(Location.country_code == country, Location.city == city)
            )
            if loc is None:
                loc = Location(
                    country_code=country,
                    city=city,
                    names={"en": f"{city}, {country}" if city else country},
                )
                db.add(loc)
                await db.flush()
            server = await db.scalar(select(Server).where(Server.hostname == hostname))
            if server is None:
                server = Server(hostname=hostname, location_id=loc.id)
                db.add(server)
            token = new_node_token()
            server.location_id = loc.id
            server.public_ipv4 = v4
            server.public_ipv6 = v6
            server.endpoint_port = port
            server.wg_public_key = wg_public_key
            server.max_peers = max_peers
            server.status = "active"
            server.agent_token_hash = ctx.tokens.hash_opaque(token)
            await db.flush()
            audit.record(
                db,
                action="cli.node_registered",
                actor_type=ActorType.SYSTEM,
                target_type="server",
                target_id=server.id,
                details={"hostname": hostname, "country": country},
            )
            await db.commit()
            print(json.dumps({"server_id": str(server.id), "token": token}))
            return 0
    finally:
        await ctx.close()


INVITE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I


async def create_invites(count: int, days: int, plan_code: str, valid_days: int) -> int:
    """Single-use free-days codes for the closed test; prints one code per line."""
    import datetime as dt
    import secrets

    from app.models import PromoCode
    from app.models.base import utcnow

    ctx = AppContext.create(get_settings(), null_pool=True)
    try:
        async with ctx.sessionmaker() as db:
            plan = await db.scalar(select(Plan).where(Plan.code == plan_code))
            if plan is None:
                print(f"no plan {plan_code!r} (run bootstrap-catalog)", file=sys.stderr)
                return 1
            codes = []
            for _ in range(count):
                body = "".join(secrets.choice(INVITE_ALPHABET) for _ in range(8))
                code = f"INV-{body[:4]}-{body[4:]}"
                db.add(
                    PromoCode(
                        code=code,
                        kind="free_days",
                        free_days=days,
                        plan_id=plan.id,
                        max_redemptions=1,
                        valid_until=utcnow() + dt.timedelta(days=valid_days),
                    )
                )
                codes.append(code)
            audit.record(
                db,
                action="cli.invites_created",
                actor_type=ActorType.SYSTEM,
                details={"count": count, "days": days, "plan": plan_code},
            )
            await db.commit()
    finally:
        await ctx.close()
    bot = get_settings().telegram_bot_username
    for code in codes:
        print(f"{code}  https://t.me/{bot}?start={code}" if bot else code)
    return 0


async def set_setting(key: str, raw_value: str) -> int:
    import json

    try:
        value = json.loads(raw_value)
    except json.JSONDecodeError:
        print('value must be JSON, e.g. true, 14, "trial", [3,1]', file=sys.stderr)
        return 1
    ctx = AppContext.create(get_settings(), null_pool=True)
    try:
        async with ctx.sessionmaker() as db:
            try:
                stored = await settings_service.set_value(db, key, value, actor_id=None)
            except Exception as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 1
            audit.record(
                db,
                action="cli.setting_changed",
                actor_type=ActorType.SYSTEM,
                target_type="setting",
                target_id=key,
                details={"after": stored},
            )
            await db.commit()
            print(f"{key} = {json.dumps(stored)}")
            return 0
    finally:
        await ctx.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    g = sub.add_parser("grant-role")
    g.add_argument("email")
    g.add_argument("role", choices=[r.value for r in Role])
    cs = sub.add_parser("create-staff", help="e.g. create-staff you@example.com superadmin")
    cs.add_argument("email")
    cs.add_argument("role")
    sub.add_parser("seed-dev")
    p = sub.add_parser("set-price", help="e.g. set-price standard month 3 USD 12.99")
    p.add_argument("plan")
    p.add_argument("unit", choices=["day", "month", "year"])
    p.add_argument("count", type=int, choices=range(1, 37), metavar="COUNT")
    p.add_argument("currency", choices=["USD", "EUR", "RUB"])
    p.add_argument("amount")
    sub.add_parser("cryptobot-check")
    sub.add_parser("bootstrap-catalog")
    n = sub.add_parser("node-register")
    n.add_argument("--hostname", required=True)
    n.add_argument("--country", required=True, help="ISO code, e.g. DE")
    n.add_argument("--city")
    n.add_argument("--ipv4")
    n.add_argument("--ipv6")
    n.add_argument("--port", type=int, default=51820)
    n.add_argument("--wg-public-key", required=True)
    n.add_argument("--max-peers", type=int, default=1500)
    i = sub.add_parser("create-invites")
    i.add_argument("--count", type=int, default=10)
    i.add_argument("--days", type=int, default=30)
    i.add_argument("--plan", default="standard")
    i.add_argument("--valid-days", type=int, default=60)
    st = sub.add_parser("set-setting", help="e.g. set-setting access.invite_only true")
    st.add_argument("key")
    st.add_argument("value")
    args = parser.parse_args(argv)
    if args.command == "node-register":
        return asyncio.run(
            node_register(
                args.hostname,
                args.country,
                args.city,
                args.ipv4,
                args.ipv6,
                args.port,
                args.wg_public_key,
                args.max_peers,
            )
        )
    if args.command == "create-invites":
        if not (1 <= args.count <= 500 and 1 <= args.days <= 366):
            print("count 1-500, days 1-366", file=sys.stderr)
            return 1
        return asyncio.run(create_invites(args.count, args.days, args.plan, args.valid_days))
    if args.command == "set-setting":
        return asyncio.run(set_setting(args.key, args.value))
    if args.command == "grant-role":
        return asyncio.run(grant_role(args.email, args.role))
    if args.command == "create-staff":
        return asyncio.run(create_staff(args.email, args.role))
    if args.command == "set-price":
        return asyncio.run(set_price(args.plan, args.unit, args.count, args.currency, args.amount))
    if args.command == "cryptobot-check":
        return asyncio.run(cryptobot_check())
    if args.command == "bootstrap-catalog":
        return asyncio.run(bootstrap_catalog())
    return asyncio.run(seed_dev())


if __name__ == "__main__":
    raise SystemExit(main())
