"""Game bonus wallet: a balance in hours, moved only through `move()`.

Rules that hold for every caller:
- the wallet row is locked (SELECT … FOR UPDATE) for the whole change;
- the balance can never go below zero (checked here and by a CHECK constraint);
- every change writes a ledger row, and (user, idem_key) is unique — replaying the same
  operation returns the first result instead of moving the balance again;
- nothing here can touch a subscription. Turning bonus days into VPN days is a one-way
  `redeem()`; there is no path from subscription days back into the wallet, so paid time can
  never be staked or lost.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models import BonusLedger, BonusWallet, Plan, Subscription
from app.models.enums import ActorType, Provider
from app.services import audit
from app.subscriptions import service as subs

HOURS_PER_DAY = 24


class InsufficientBonus(AppError):
    status_code = 409
    code = "insufficient_bonus"
    message = "Not enough game bonus days."


async def get_wallet(db: AsyncSession, user_id: uuid.UUID, *, lock: bool = False) -> BonusWallet:
    await db.execute(
        pg_insert(BonusWallet)
        .values(user_id=user_id)
        .on_conflict_do_nothing(index_elements=["user_id"])
    )
    stmt = select(BonusWallet).where(BonusWallet.user_id == user_id)
    if lock:
        stmt = stmt.with_for_update()
    return (await db.execute(stmt.execution_options(populate_existing=True))).scalar_one()


async def move(
    db: AsyncSession,
    user_id: uuid.UUID,
    delta_hours: int,
    kind: str,
    idem_key: str,
    *,
    round_id: uuid.UUID | None = None,
    note: str | None = None,
) -> int:
    """Change the balance by `delta_hours`; returns the balance after. Idempotent per idem_key."""
    wallet = await get_wallet(db, user_id, lock=True)
    done = await db.scalar(
        select(BonusLedger).where(BonusLedger.user_id == user_id, BonusLedger.idem_key == idem_key)
    )
    if done is not None:
        return wallet.balance_hours
    after = wallet.balance_hours + delta_hours
    if after < 0:
        raise InsufficientBonus()
    wallet.balance_hours = after
    db.add(
        BonusLedger(
            user_id=user_id,
            delta_hours=delta_hours,
            balance_after=after,
            kind=kind,
            idem_key=idem_key,
            round_id=round_id,
            note=note,
        )
    )
    await db.flush()
    return after


async def redeem(db: AsyncSession, user_id: uuid.UUID, days: int, idem_key: str) -> Subscription:
    """Turn whole bonus days into VPN days (one way). Caller commits."""
    live = await subs.get_live(db, user_id)
    plan = await db.get(Plan, live.plan_id) if live is not None else None
    if plan is None or plan.is_trial:
        plan = await db.scalar(
            select(Plan)
            .where(Plan.active.is_(True), Plan.is_trial.is_(False))
            .order_by(Plan.created_at)
            .limit(1)
        )
    if plan is None:
        raise AppError("No plan is available.", code="no_plan", status_code=409)
    before = await db.scalar(
        select(BonusLedger.id).where(
            BonusLedger.user_id == user_id, BonusLedger.idem_key == idem_key
        )
    )
    await move(db, user_id, -days * HOURS_PER_DAY, "redeem", idem_key, note=f"{days} d → VPN")
    if before is not None:  # a repeat of the same request: the days were already added
        sub = await subs.get_live(db, user_id)
        if sub is not None:
            return sub
    sub = await subs.grant_days(
        db,
        user_id=user_id,
        plan=plan,
        days=days,
        provider=Provider.PROMO,
        actor_id=user_id,
        actor_type=ActorType.USER,
        ip=None,
        reason="game_bonus",
    )
    audit.record(
        db,
        action="game.bonus_redeemed",
        actor_id=user_id,
        target_type="user",
        target_id=user_id,
        details={"days": days},
    )
    return sub
