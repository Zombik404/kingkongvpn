"""Operator commands: `python -m app.cli <command>`.

grant-role EMAIL ROLE                    give a staff role (bootstraps the first superadmin)
seed-dev                                 dev-only sample plans/prices/settings
set-price PLAN UNIT COUNT CURRENCY AMT   e.g. set-price standard month 3 USD 12.99
cryptobot-check                          verify the @CryptoBot token, list asset codes
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
                user.roles = sorted({*user.roles, role})
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
        # Placeholder dev prices — the owner sets real ones with `set-price`.
        for months, amount in ((1, "5.00"), (3, "13.00"), (6, "24.00"), (12, "42.00")):
            await set_price("standard", "month", months, "USD", amount, quiet=True)
        print("seeded dev plans: trial, standard (1/3/6/12 months, placeholder USD prices)")
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
    crypto = sorted({str(c.get("code")) for c in currencies if c.get("is_blockchain")})
    fiat = sorted({str(c.get("code")) for c in currencies if c.get("is_fiat")})
    print("crypto assets:", ", ".join(crypto) or "?")
    print("fiat:", ", ".join(fiat) or "?")
    missing = [a for a in settings.cryptobot_accepted_assets if crypto and a not in crypto]
    print("configured CRYPTOBOT_ACCEPTED_ASSETS:", ", ".join(settings.cryptobot_accepted_assets))
    if missing:
        print(f"WARNING: not offered by the API: {', '.join(missing)}", file=sys.stderr)
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    g = sub.add_parser("grant-role")
    g.add_argument("email")
    g.add_argument("role", choices=[r.value for r in Role])
    sub.add_parser("seed-dev")
    p = sub.add_parser("set-price", help="e.g. set-price standard month 3 USD 12.99")
    p.add_argument("plan")
    p.add_argument("unit", choices=["day", "month", "year"])
    p.add_argument("count", type=int, choices=range(1, 37), metavar="COUNT")
    p.add_argument("currency", choices=["USD", "EUR", "RUB"])
    p.add_argument("amount")
    sub.add_parser("cryptobot-check")
    args = parser.parse_args(argv)
    if args.command == "grant-role":
        return asyncio.run(grant_role(args.email, args.role))
    if args.command == "set-price":
        return asyncio.run(set_price(args.plan, args.unit, args.count, args.currency, args.amount))
    if args.command == "cryptobot-check":
        return asyncio.run(cryptobot_check())
    return asyncio.run(seed_dev())


if __name__ == "__main__":
    raise SystemExit(main())
