"""Background tasks. Each periodic task opens its own short-lived context (NullPool engine),
so tasks are independent of worker pool type and never share connections across loops."""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import smtplib
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import delete, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.context import AppContext
from app.games import boards
from app.games import service as games_service
from app.models import AuthSession, User, UserActionToken
from app.models.base import utcnow
from app.models.enums import UserStatus
from app.notifications.email import EmailJob, render, send_smtp
from app.notifications.telegram import TelegramJob, TelegramSendError, send_sync
from app.payments import service as payments
from app.services import settings as settings_service
from app.services.users import DELETED_ACCOUNT_RETENTION_DAYS
from app.subscriptions import service as subs
from app.vpn import service as vpn_service
from app.workers.celery_app import celery_app

log = logging.getLogger(__name__)


async def _with_db[T](
    fn: Callable[[AppContext, AsyncSession], Awaitable[T]], ctx: AppContext | None = None
) -> T:
    own = ctx is None
    context = ctx or AppContext.create(get_settings(), null_pool=True)
    try:
        async with context.sessionmaker() as session:
            return await fn(context, session)
    finally:
        if own:
            await context.close()


@celery_app.task(
    name="email.send",
    autoretry_for=(smtplib.SMTPException, OSError),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=8,
)
def send_email(job: dict[str, Any]) -> None:
    settings = get_settings()
    send_smtp(render(EmailJob.from_dict(job), settings), settings)


async def purge_deleted_users(ctx: AppContext, db: AsyncSession) -> int:
    cutoff = utcnow() - dt.timedelta(days=DELETED_ACCOUNT_RETENTION_DAYS)
    result = await db.execute(
        delete(User).where(User.status == UserStatus.DELETED, User.deleted_at <= cutoff)
    )
    await db.commit()
    return int(getattr(result, "rowcount", 0) or 0)


async def cleanup_tokens(ctx: AppContext, db: AsyncSession) -> int:
    """Drop expired/revoked sessions (cascades to refresh tokens) and stale action tokens."""
    now = utcnow()
    week_ago = now - dt.timedelta(days=7)
    a = await db.execute(
        delete(AuthSession).where(
            or_(AuthSession.expires_at <= week_ago, AuthSession.revoked_at <= week_ago)
        )
    )
    b = await db.execute(
        delete(UserActionToken).where(
            or_(UserActionToken.expires_at <= week_ago, UserActionToken.used_at <= week_ago)
        )
    )
    await db.commit()
    c = await vpn_service.purge_removed_assignments(db, dt.timedelta(days=1))
    c += await vpn_service.release_revoked_addresses(db, dt.timedelta(days=30))
    c += await vpn_service.purge_old_usage(db, keep_days=90)
    return int(getattr(a, "rowcount", 0) or 0) + int(getattr(b, "rowcount", 0) or 0) + c


async def release_idle_peers(ctx: AppContext, db: AsyncSession) -> int:
    hours = int(await settings_service.get_value(db, "peers.idle_ttl_hours"))
    if hours <= 0:
        return 0
    return await vpn_service.release_idle_assignments(db, dt.timedelta(hours=hours))


@celery_app.task(name="vpn.release_idle_peers")
def release_idle_peers_task() -> int:
    return asyncio.run(_with_db(release_idle_peers))


@celery_app.task(name="subscriptions.process_due")
def process_due_task() -> int:
    return asyncio.run(_with_db(lambda c, s: subs.process_due(c, s)))


@celery_app.task(name="subscriptions.send_reminders")
def send_reminders_task() -> int:
    return asyncio.run(_with_db(lambda c, s: subs.send_reminders(c, s)))


@celery_app.task(name="users.purge_deleted")
def purge_deleted_task() -> int:
    return asyncio.run(_with_db(purge_deleted_users))


@celery_app.task(name="auth.cleanup_tokens")
def cleanup_tokens_task() -> int:
    return asyncio.run(_with_db(cleanup_tokens))


@celery_app.task(name="games.run_timers")
def game_timers_task() -> int:
    """Expired turn/bet timers at game tables, and closing tables nobody uses."""
    return asyncio.run(_with_db(lambda c, s: games_service.run_timers(c, s)))


async def run_seasons(ctx: AppContext, db: AsyncSession) -> int:
    """Open this week's/month's season, close finished ones (prizes once), tell the winners."""
    cfg = await games_service.config(db)
    await boards.ensure_current(db, cfg)
    await db.commit()
    closed = 0
    for season_id in await boards.due(db):
        prizes = await boards.finalize(db, cfg, season_id)
        await db.commit()
        closed += 1
        await games_service.send_notices(
            ctx,
            [
                (
                    "game_season_reward",
                    uid,
                    {
                        "place": str(p["rank"]),
                        "season": p["season"],
                        "xp": str(p.get("xp", 0)),
                        "extra": f" · «{p['title']}»" if p.get("title") else "",
                    },
                )
                for uid, p in prizes
                if p["rank"] <= 10
            ],
        )
    return closed


@celery_app.task(name="games.seasons")
def game_seasons_task() -> int:
    """Season rotation: weekly and monthly seasons, final tables and prizes."""
    return asyncio.run(_with_db(run_seasons))


@celery_app.task(name="payments.poll_pending")
def poll_payments_task() -> dict[str, int]:
    return asyncio.run(_with_db(lambda c, s: payments.poll_pending(c, s)))


@celery_app.task(
    name="telegram.send",
    autoretry_for=(TelegramSendError,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=8,
)
def send_telegram(job: dict[str, Any]) -> None:
    send_sync(TelegramJob.from_dict(job), get_settings())
