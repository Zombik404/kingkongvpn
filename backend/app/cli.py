"""Operator commands: `python -m app.cli <command>`.

grant-role EMAIL ROLE      give a staff role (bootstraps the first superadmin)
seed-dev                   development-only sample plans/prices/settings (no servers, no metrics)
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from sqlalchemy import select

from app.core.config import get_settings
from app.core.context import AppContext
from app.models import Plan, PlanPrice, User
from app.models.enums import ActorType, Role
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
            trial = Plan(
                code="trial",
                names={"en": "Trial", "ru": "Пробный"},
                device_limit=2,
                is_trial=True,
                sort_order=0,
            )
            std = Plan(
                code="standard",
                names={"en": "Standard", "ru": "Стандарт"},
                device_limit=5,
                sort_order=10,
            )
            db.add_all([trial, std])
            await db.flush()
            # Placeholder dev prices — real prices are set by the owner via the admin API.
            db.add_all(
                [
                    PlanPrice(
                        plan_id=std.id,
                        period_unit="month",
                        period_count=1,
                        currency="EUR",
                        amount_minor=500,
                    ),
                    PlanPrice(
                        plan_id=std.id,
                        period_unit="year",
                        period_count=1,
                        currency="EUR",
                        amount_minor=4800,
                    ),
                ]
            )
            await settings_service.set_value(db, "trial.enabled", True, actor_id=None)
            await db.commit()
            print("seeded dev plans: trial, standard")
            return 0
    finally:
        await ctx.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    g = sub.add_parser("grant-role")
    g.add_argument("email")
    g.add_argument("role", choices=[r.value for r in Role])
    sub.add_parser("seed-dev")
    args = parser.parse_args(argv)
    if args.command == "grant-role":
        return asyncio.run(grant_role(args.email, args.role))
    return asyncio.run(seed_dev())


if __name__ == "__main__":
    raise SystemExit(main())
