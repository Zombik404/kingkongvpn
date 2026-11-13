"""Profile, data export and account deletion."""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import AppContext
from app.core.errors import InvalidCredentials, NotAuthenticated
from app.models import (
    AuthSession,
    BonusLedger,
    BonusWallet,
    Device,
    DeviceUsageDaily,
    GameProfile,
    GameReward,
    NotificationPreference,
    Payment,
    ReferralMilestone,
    ReferralReward,
    Subscription,
    User,
)
from app.models.base import utcnow
from app.models.enums import ActorType, DeviceStatus, UserStatus
from app.schemas.domain import UserOut
from app.security import rate_limit as rl
from app.security.principal import ClientInfo
from app.security.telegram import validate_init_data
from app.services import audit
from app.subscriptions import service as subs

DELETED_ACCOUNT_RETENTION_DAYS = 30


def user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        email_verified=user.email_verified_at is not None,
        locale=user.locale,
        roles=list(user.roles),
        mfa_enabled=user.mfa_enabled,
        has_telegram=user.telegram_id is not None,
        created_at=user.created_at,
    )


def _iso(v: Any) -> Any:
    return v.isoformat() if hasattr(v, "isoformat") else (str(v) if v is not None else None)


async def export_data(db: AsyncSession, user: User) -> dict[str, Any]:
    """Everything we hold about the user, machine-readable (GDPR Art. 15/20 style)."""
    devices = (await db.scalars(select(Device).where(Device.user_id == user.id))).all()
    subscriptions = (
        await db.scalars(select(Subscription).where(Subscription.user_id == user.id))
    ).all()
    payments = (await db.scalars(select(Payment).where(Payment.user_id == user.id))).all()
    sessions = (await db.scalars(select(AuthSession).where(AuthSession.user_id == user.id))).all()
    usage = (
        await db.scalars(
            select(DeviceUsageDaily)
            .join(Device, Device.id == DeviceUsageDaily.device_id)
            .where(Device.user_id == user.id)
            .order_by(DeviceUsageDaily.day)
        )
    ).all()
    prefs = await db.get(NotificationPreference, user.id)
    profile = await db.get(GameProfile, user.id)
    wallet = await db.get(BonusWallet, user.id)
    ledger = (
        await db.scalars(
            select(BonusLedger)
            .where(BonusLedger.user_id == user.id)
            .order_by(BonusLedger.created_at)
        )
    ).all()
    invited = await db.scalar(
        select(func.count()).select_from(User).where(User.referred_by_id == user.id)
    )
    rewards = (
        await db.scalars(select(ReferralReward).where(ReferralReward.referrer_id == user.id))
    ).all()
    milestones = (
        await db.scalars(select(ReferralMilestone).where(ReferralMilestone.user_id == user.id))
    ).all()
    from app.models import Achievement, PlayDay, Season, SeasonStat, UserAchievement, XpEvent

    xp_events = (
        await db.scalars(
            select(XpEvent).where(XpEvent.user_id == user.id).order_by(XpEvent.created_at)
        )
    ).all()
    unlocked = (
        await db.execute(
            select(Achievement.code, UserAchievement.created_at)
            .join(Achievement, Achievement.id == UserAchievement.achievement_id)
            .where(UserAchievement.user_id == user.id)
        )
    ).all()
    days = (await db.scalars(select(PlayDay.day).where(PlayDay.user_id == user.id))).all()
    season_stats = (
        await db.execute(
            select(Season.name, Season.kind, SeasonStat)
            .join(SeasonStat, SeasonStat.season_id == Season.id)
            .where(SeasonStat.user_id == user.id)
        )
    ).all()
    game_rewards = (await db.scalars(select(GameReward).where(GameReward.user_id == user.id))).all()
    return {
        "exported_at": utcnow().isoformat(),
        "account": {
            "id": str(user.id),
            "email": user.email,
            "email_verified_at": _iso(user.email_verified_at),
            "locale": user.locale,
            "telegram_linked": user.telegram_id is not None,
            "mfa_enabled": user.mfa_enabled,
            "created_at": _iso(user.created_at),
            "last_login_at": _iso(user.last_login_at),
        },
        "devices": [
            {
                "id": str(d.id),
                "name": d.name,
                "platform": d.platform,
                "public_key": d.public_key,
                "ipv4": _iso(d.ipv4),
                "ipv6": _iso(d.ipv6),
                "status": d.status,
                "created_at": _iso(d.created_at),
                "revoked_at": _iso(d.revoked_at),
                "last_handshake_at": _iso(d.last_handshake_at),
            }
            for d in devices
        ],
        "subscriptions": [
            {
                "id": str(s.id),
                "status": s.status,
                "provider": s.provider,
                "period_start": _iso(s.current_period_start),
                "period_end": _iso(s.current_period_end),
            }
            for s in subscriptions
        ],
        "payments": [
            {
                "id": str(p.id),
                "provider": p.provider,
                "amount_minor": p.amount_minor,
                "currency": p.currency,
                "status": p.status,
                "kind": p.kind,
                "created_at": _iso(p.created_at),
            }
            for p in payments
        ],
        "sessions": [
            {
                "id": str(s.id),
                "created_at": _iso(s.created_at),
                "last_used_at": _iso(s.last_used_at),
                "user_agent": s.user_agent,
                "ip_prefix": s.ip_prefix,
                "revoked_at": _iso(s.revoked_at),
            }
            for s in sessions
        ],
        # Traffic totals per device per day (no destinations or contents are ever recorded).
        "traffic_daily": [
            {
                "device_id": str(u.device_id),
                "day": _iso(u.day),
                "download_bytes": u.download_bytes,
                "upload_bytes": u.upload_bytes,
            }
            for u in usage
        ],
        "notification_preferences": (
            {
                "email_service": prefs.email_service,
                "email_marketing": prefs.email_marketing,
                "telegram": prefs.telegram,
                "push": prefs.push,
            }
            if prefs
            else None
        ),
        "referrals": {
            "code": user.referral_code,
            "invited_by_someone": user.referred_by_id is not None,
            "invited_users": int(invited or 0),
            "rewards": [
                {"bonus_days": r.bonus_days, "created_at": _iso(r.created_at)} for r in rewards
            ],
            "ranks": [
                {"level": m.level, "bonus_days": m.bonus_days, "created_at": _iso(m.created_at)}
                for m in milestones
            ],
        },
        "games": {
            "profile": (
                {
                    "nickname": profile.nickname,
                    "rounds": profile.rounds,
                    "wins": profile.wins,
                    "losses": profile.losses,
                    "pushes": profile.pushes,
                    "blackjacks": profile.blackjacks,
                    "chips": profile.chips,
                    "best_win": profile.best_win,
                    "best_win_stake": profile.best_win_stake,
                }
                if profile
                else None
            ),
            "progress": (
                {
                    "xp": profile.xp,
                    "level": profile.level,
                    "avatar": profile.avatar,
                    "title": profile.title,
                    "frame": profile.frame,
                    "day_streak": profile.day_streak,
                    "best_day_streak": profile.best_day_streak,
                    "excluded_from_boards": profile.excluded_at is not None,
                }
                if profile
                else None
            ),
            "xp_events": [
                {"amount": e.amount, "kind": e.kind, "created_at": _iso(e.created_at)}
                for e in xp_events
            ],
            "achievements": [{"code": c, "unlocked_at": _iso(at)} for c, at in unlocked],
            "days_played": sorted(d.isoformat() for d in days),
            "seasons": [
                {"season": name, "kind": kind, "rounds": st.rounds, "wins": st.wins, "xp": st.xp}
                for name, kind, st in season_stats
            ],
            "rewards": [
                {
                    "source": r.source,
                    "xp": r.xp,
                    "title": r.title,
                    "frame": r.frame,
                    "bonus_days": r.bonus_days,
                    "created_at": _iso(r.created_at),
                }
                for r in game_rewards
            ],
            "bonus_hours": wallet.balance_hours if wallet else 0,
            "bonus_ledger": [
                {
                    "delta_hours": e.delta_hours,
                    "balance_after": e.balance_after,
                    "kind": e.kind,
                    "created_at": _iso(e.created_at),
                }
                for e in ledger
            ],
        },
    }


async def delete_account(
    ctx: AppContext,
    db: AsyncSession,
    user_id: Any,
    client: ClientInfo,
    *,
    password: str | None = None,
    telegram_init_data: str | None = None,
) -> None:
    """Anonymise immediately; the row itself is purged after the retention window.

    The owner proves it's them again: with the password, or — for an account made in Telegram,
    which has none — with fresh `initData` from the Mini App for the same Telegram user.
    Personal identifiers (email, password hash, Telegram ID, TOTP seed, game nickname, referral
    code) are cleared now so nothing personal lingers. Payment rows are kept (accounting law)
    but lose their link to the user at purge time (FK SET NULL).
    """
    await ctx.limiter.hit(rl.LOGIN_PER_ACCOUNT, f"delete:{user_id}")
    user = await db.get(User, user_id, with_for_update=True)
    assert user is not None
    if user.password_hash is not None:
        if not password or not (await ctx.passwords.verify(user.password_hash, password)).ok:
            raise InvalidCredentials("Password is incorrect.")
    else:
        try:
            tg = validate_init_data(
                telegram_init_data or "",
                ctx.settings.telegram_bot_token.get_secret_value(),
                max_age=dt.timedelta(seconds=ctx.settings.telegram_webapp_max_age_seconds),
                now=utcnow(),
            )
        except NotAuthenticated as exc:
            raise InvalidCredentials("Confirm the deletion from Telegram.") from exc
        if user.telegram_id is None or tg.id != user.telegram_id:
            raise InvalidCredentials("Confirm the deletion from Telegram.")
    now = utcnow()
    live = await subs.get_live(db, user.id, lock=True)
    if live is not None:
        await subs.revoke(
            db,
            live,
            actor_id=user.id,
            actor_type=ActorType.USER,
            ip=client.ip,
            reason="account_deleted",
        )
    await db.execute(
        update(Device)
        .where(Device.user_id == user.id, Device.status == DeviceStatus.ACTIVE)
        .values(status=DeviceStatus.REVOKED.value, revoked_at=now)
    )
    await subs.revoke_peer_access(db, user.id)
    await db.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=now, revoke_reason="account_deleted")
    )
    user.status = UserStatus.DELETED.value
    user.deleted_at = now
    user.email = None
    user.password_hash = None
    user.telegram_id = None
    user.totp_secret_encrypted = None
    user.totp_enabled_at = None
    user.roles = []
    user.referral_code = None
    user.token_version += 1
    profile = await db.get(GameProfile, user.id, with_for_update=True)
    if profile is not None:  # the nickname may be a real name: gone from boards at once
        profile.nickname = "Deleted player"
        profile.avatar = "🦍"
        profile.title = None
    from app.models import SeasonResult

    await db.execute(  # and from the frozen tables of past seasons
        update(SeasonResult)
        .where(SeasonResult.user_id == user.id)
        .values(nickname="Deleted player")
    )
    audit.record(
        db,
        action="user.deleted",
        actor_id=user.id,
        target_type="user",
        target_id=user.id,
        ip=client.ip,
    )
    await db.commit()
