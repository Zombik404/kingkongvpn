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
from app.games import service as games_service
from app.models import AuthSession, User, UserActionToken
from app.models.base import utcnow
from app.models.enums import UserStatus
from app.notifications.email import EmailJob, render, send_smtp
from app.notifications.telegram import TelegramJob, TelegramSendError, send_sync
from app.payments import service as payments
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
    c += await vpn_service.purge_old_usage(db, keep_days=90)
    return int(getattr(a, "rowcount", 0) or 0) + int(getattr(b, "rowcount", 0) or 0) + c


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
