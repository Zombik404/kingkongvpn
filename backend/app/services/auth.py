"""Authentication flows (ADR-007).

Every endpoint that takes an email answers identically whether or not an account exists
(no enumeration). Refresh tokens rotate on every use; presenting an already-used token
revokes the whole session (theft detection).
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import AppContext
from app.core.errors import AppError, Conflict, InvalidCredentials, InvalidToken, NotAuthenticated
from app.i18n import normalize
from app.models import AuthSession, RefreshToken, User, UserActionToken
from app.models.base import utcnow
from app.models.enums import ActionTokenPurpose, ActorType, AuditResult, UserStatus
from app.notifications.email import EmailJob
from app.security import rate_limit as rl
from app.security import totp
from app.security.principal import ClientInfo, Principal
from app.security.rbac import is_staff
from app.security.telegram import validate_init_data
from app.services import audit

STAFF_SESSION_TTL = dt.timedelta(hours=12)


class AccountSuspended(AppError):
    status_code = 403
    code = "account_suspended"
    message = "This account is suspended. Contact support."


class EmailNotVerified(AppError):
    status_code = 403
    code = "email_not_verified"
    message = "Confirm your email address first. We can send the link again."


class InvalidMfaCode(AppError):
    status_code = 401
    code = "invalid_mfa_code"
    message = "The code is incorrect or was already used."


@dataclass(frozen=True)
class TokenPair:
    access_token: str
    refresh_token: str
    expires_in: int
    session_id: uuid.UUID


@dataclass(frozen=True)
class MfaRequired:
    mfa_token: str


@dataclass(frozen=True)
class TotpSetup:
    secret: str
    otpauth_uri: str


def _normalize_email(email: str) -> str:
    return email.strip().lower()


class AuthService:
    def __init__(self, ctx: AppContext, session: AsyncSession) -> None:
        self.ctx = ctx
        self.db = session

    # --- helpers ---------------------------------------------------------------
    async def _user_by_email(self, email: str) -> User | None:
        return await self.db.scalar(select(User).where(User.email == email))

    def _session_ttl(self, user: User) -> dt.timedelta:
        if is_staff(user.roles):
            return STAFF_SESSION_TTL
        return dt.timedelta(days=self.ctx.settings.refresh_token_ttl_days)

    async def _new_action_token(
        self, user: User, purpose: ActionTokenPurpose, ttl: dt.timedelta
    ) -> str:
        now = utcnow()
        # Only the newest link of a given purpose stays valid.
        await self.db.execute(
            update(UserActionToken)
            .where(
                UserActionToken.user_id == user.id,
                UserActionToken.purpose == purpose,
                UserActionToken.used_at.is_(None),
            )
            .values(used_at=now)
        )
        raw = self.ctx.tokens.new_opaque()
        self.db.add(
            UserActionToken(
                user_id=user.id,
                purpose=purpose,
                token_hash=self.ctx.tokens.hash_opaque(raw),
                created_at=now,
                expires_at=now + ttl,
            )
        )
        return raw

    async def _consume_action_token(self, raw: str, purpose: ActionTokenPurpose) -> User:
        row = await self.db.scalar(
            select(UserActionToken)
            .where(
                UserActionToken.token_hash == self.ctx.tokens.hash_opaque(raw),
                UserActionToken.purpose == purpose,
            )
            .with_for_update()
        )
        now = utcnow()
        if row is None or row.used_at is not None or row.expires_at <= now:
            raise InvalidToken()
        user = await self.db.get(User, row.user_id, with_for_update=True)
        if user is None or user.status != UserStatus.ACTIVE:
            raise InvalidToken()
        row.used_at = now
        return user

    def _verify_link(self, raw: str) -> str:
        return f"{self.ctx.settings.public_web_url}/verify-email?token={raw}"

    def _reset_link(self, raw: str) -> str:
        return f"{self.ctx.settings.public_web_url}/reset-password?token={raw}"

    def _verify_job(self, user: User, raw: str) -> EmailJob:
        assert user.email is not None
        return EmailJob(
            "verify_email",
            user.email,
            user.locale,
            {"hours": str(self.ctx.settings.email_token_ttl_hours)},
            self._verify_link(raw),
        )

    async def _start_session(
        self, user: User, client: ClientInfo, *, mfa_verified: bool, action: str
    ) -> TokenPair:
        now = utcnow()
        ttl = self._session_ttl(user)
        sess = AuthSession(
            user_id=user.id,
            created_at=now,
            last_used_at=now,
            expires_at=now + ttl,
            mfa_verified=mfa_verified,
            user_agent=(client.user_agent or "")[:256] or None,
            ip_prefix=audit.ip_prefix(client.ip),
        )
        self.db.add(sess)
        await self.db.flush()
        raw = self.ctx.tokens.new_opaque()
        self.db.add(
            RefreshToken(
                session_id=sess.id,
                token_hash=self.ctx.tokens.hash_opaque(raw),
                created_at=now,
                expires_at=now + ttl,
            )
        )
        user.last_login_at = now
        audit.record(
            self.db,
            action=action,
            actor_id=user.id,
            target_type="user",
            target_id=user.id,
            ip=client.ip,
            details={"mfa": mfa_verified, "session": str(sess.id)},
        )
        await self.db.commit()
        return self._pair(user, sess, raw)

    def _pair(self, user: User, sess: AuthSession, raw_refresh: str) -> TokenPair:
        amr = ["pwd", "otp"] if sess.mfa_verified else ["pwd"]
        access, _ = self.ctx.tokens.issue_access(
            user_id=user.id,
            session_id=sess.id,
            roles=list(user.roles),
            ver=user.token_version,
            amr=amr,
        )
        return TokenPair(access, raw_refresh, self.ctx.settings.jwt_access_ttl_seconds, sess.id)

    async def _revoke_sessions(
        self, user_id: uuid.UUID, reason: str, except_session: uuid.UUID | None = None
    ) -> None:
        stmt = (
            update(AuthSession)
            .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
            .values(revoked_at=utcnow(), revoke_reason=reason)
        )
        if except_session is not None:
            stmt = stmt.where(AuthSession.id != except_session)
        await self.db.execute(stmt)

    # --- registration & verification -------------------------------------------
    async def register(self, email: str, password: str, locale: str, client: ClientInfo) -> None:
        email = _normalize_email(email)
        await self.ctx.limiter.hit(rl.REGISTER_PER_IP, client.ip or "unknown")
        await self.ctx.limiter.hit(rl.EMAIL_PER_ADDRESS, email)
        self.ctx.passwords.validate_policy(password, email=email)
        password_hash = await self.ctx.passwords.hash(password)

        existing = await self._user_by_email(email)
        job: EmailJob | None = None
        if existing is None:
            user = User(email=email, password_hash=password_hash, locale=locale)
            self.db.add(user)
            try:
                await self.db.flush()
            except IntegrityError:
                await self.db.rollback()
                existing = await self._user_by_email(email)
            else:
                raw = await self._new_action_token(
                    user,
                    ActionTokenPurpose.VERIFY_EMAIL,
                    dt.timedelta(hours=self.ctx.settings.email_token_ttl_hours),
                )
                audit.record(
                    self.db,
                    action="auth.register",
                    actor_id=user.id,
                    target_type="user",
                    target_id=user.id,
                    ip=client.ip,
                )
                job = self._verify_job(user, raw)
        if existing is not None and existing.email:
            if existing.email_verified_at is None and existing.status == UserStatus.ACTIVE:
                raw = await self._new_action_token(
                    existing,
                    ActionTokenPurpose.VERIFY_EMAIL,
                    dt.timedelta(hours=self.ctx.settings.email_token_ttl_hours),
                )
                job = self._verify_job(existing, raw)
            elif existing.status == UserStatus.ACTIVE:
                job = EmailJob(
                    "account_exists",
                    existing.email,
                    existing.locale,
                    {},
                    f"{self.ctx.settings.public_web_url}/forgot-password",
                )
        await self.db.commit()
        if job:
            await self.ctx.mailer.dispatch(job)

    async def verify_email(self, raw: str) -> None:
        user = await self._consume_action_token(raw, ActionTokenPurpose.VERIFY_EMAIL)
        if user.email_verified_at is None:
            user.email_verified_at = utcnow()
        audit.record(
            self.db,
            action="auth.email_verified",
            actor_id=user.id,
            target_type="user",
            target_id=user.id,
        )
        await self.db.commit()

    async def resend_verification(self, email: str, client: ClientInfo) -> None:
        email = _normalize_email(email)
        await self.ctx.limiter.hit(rl.EMAIL_PER_IP, client.ip or "unknown")
        await self.ctx.limiter.hit(rl.EMAIL_PER_ADDRESS, email)
        user = await self._user_by_email(email)
        if user is None or user.email_verified_at is not None or not user.is_active:
            return
        raw = await self._new_action_token(
            user,
            ActionTokenPurpose.VERIFY_EMAIL,
            dt.timedelta(hours=self.ctx.settings.email_token_ttl_hours),
        )
        await self.db.commit()
        await self.ctx.mailer.dispatch(self._verify_job(user, raw))

    # --- login / MFA -------------------------------------------------------------
    async def login(self, email: str, password: str, client: ClientInfo) -> TokenPair | MfaRequired:
        email = _normalize_email(email)
        await self.ctx.limiter.hit(rl.LOGIN_PER_IP, client.ip or "unknown")
        await self.ctx.limiter.hit(rl.LOGIN_PER_ACCOUNT, email)
        user = await self._user_by_email(email)
        result = await self.ctx.passwords.verify(user.password_hash if user else None, password)
        if user is None or not result.ok or user.status == UserStatus.DELETED:
            audit.record(
                self.db,
                action="auth.login",
                actor_id=user.id if user else None,
                actor_type=ActorType.USER if user else ActorType.ANONYMOUS,
                target_type="user",
                target_id=user.id if user else None,
                result=AuditResult.FAILURE,
                ip=client.ip,
                details={"reason": "bad_credentials"},
            )
            await self.db.commit()
            raise InvalidCredentials()
        if user.status == UserStatus.SUSPENDED:
            raise AccountSuspended()
        if user.email_verified_at is None:
            raise EmailNotVerified()
        if result.needs_rehash:
            user.password_hash = await self.ctx.passwords.hash(password)
        await self.ctx.limiter.reset(rl.LOGIN_PER_ACCOUNT, email)
        if user.mfa_enabled:
            await self.db.commit()
            return MfaRequired(
                self.ctx.tokens.issue_mfa_challenge(user_id=user.id, ver=user.token_version)
            )
        return await self._start_session(user, client, mfa_verified=False, action="auth.login")

    async def complete_mfa(self, mfa_token: str, code: str, client: ClientInfo) -> TokenPair:
        claims = self.ctx.tokens.decode_mfa_challenge(mfa_token)
        await self.ctx.limiter.hit(rl.MFA_PER_ACCOUNT, str(claims.sub))
        user = await self.db.get(User, claims.sub, with_for_update=True)
        if (
            user is None
            or not user.is_active
            or user.token_version != claims.ver
            or not user.mfa_enabled
            or user.totp_secret_encrypted is None
        ):
            raise NotAuthenticated("Invalid or expired token.")
        self._check_totp(user, code, client, action="auth.mfa_verify")
        return await self._start_session(user, client, mfa_verified=True, action="auth.login")

    def _check_totp(self, user: User, code: str, client: ClientInfo, *, action: str) -> None:
        assert user.totp_secret_encrypted is not None
        secret = self.ctx.cipher.decrypt(
            user.totp_secret_encrypted, context=b"totp:" + user.id.bytes
        )
        counter = totp.verify(secret, code, last_counter=user.totp_last_counter)
        if counter is None:
            raise InvalidMfaCode()
        user.totp_last_counter = counter

    # --- refresh / logout --------------------------------------------------------
    async def refresh(self, raw: str, client: ClientInfo) -> TokenPair:
        await self.ctx.limiter.hit(rl.REFRESH_PER_IP, client.ip or "unknown")
        token = await self.db.scalar(
            select(RefreshToken)
            .where(RefreshToken.token_hash == self.ctx.tokens.hash_opaque(raw))
            .with_for_update()
        )
        if token is None:
            raise NotAuthenticated("Invalid or expired token.")
        sess = await self.db.get(AuthSession, token.session_id, with_for_update=True)
        user = await self.db.get(User, sess.user_id) if sess else None
        now = utcnow()
        if sess is None or user is None:
            raise NotAuthenticated("Invalid or expired token.")
        if token.used_at is not None:
            # Reuse of a rotated token: assume theft, kill the whole family.
            if sess.revoked_at is None:
                sess.revoked_at = now
                sess.revoke_reason = "refresh_reuse"
                audit.record(
                    self.db,
                    action="auth.refresh_reuse_detected",
                    actor_id=user.id,
                    target_type="session",
                    target_id=sess.id,
                    result=AuditResult.DENIED,
                    ip=client.ip,
                )
            await self.db.commit()
            raise NotAuthenticated("Invalid or expired token.")
        if (
            sess.revoked_at is not None
            or token.expires_at <= now
            or sess.expires_at <= now
            or not user.is_active
        ):
            raise NotAuthenticated("Invalid or expired token.")
        ttl = self._session_ttl(user)
        new_raw = self.ctx.tokens.new_opaque()
        new = RefreshToken(
            session_id=sess.id,
            token_hash=self.ctx.tokens.hash_opaque(new_raw),
            created_at=now,
            expires_at=now + ttl,
        )
        self.db.add(new)
        await self.db.flush()
        token.used_at = now
        token.replaced_by_id = new.id
        sess.last_used_at = now
        sess.expires_at = now + ttl
        await self.db.commit()
        return self._pair(user, sess, new_raw)

    async def logout(self, principal: Principal, client: ClientInfo) -> None:
        sess = await self.db.get(AuthSession, principal.session.id, with_for_update=True)
        if sess and sess.revoked_at is None:
            sess.revoked_at = utcnow()
            sess.revoke_reason = "logout"
        audit.record(
            self.db,
            action="auth.logout",
            actor_id=principal.user.id,
            target_type="session",
            target_id=principal.session.id,
            ip=client.ip,
        )
        await self.db.commit()

    async def logout_all(self, principal: Principal, client: ClientInfo) -> None:
        user = await self.db.get(User, principal.user.id, with_for_update=True)
        assert user is not None
        await self._revoke_sessions(user.id, "logout_all")
        user.token_version += 1
        audit.record(
            self.db,
            action="auth.logout_all",
            actor_id=user.id,
            target_type="user",
            target_id=user.id,
            ip=client.ip,
        )
        await self.db.commit()

    # --- passwords ---------------------------------------------------------------
    async def request_password_reset(self, email: str, client: ClientInfo) -> None:
        email = _normalize_email(email)
        await self.ctx.limiter.hit(rl.EMAIL_PER_IP, client.ip or "unknown")
        await self.ctx.limiter.hit(rl.EMAIL_PER_ADDRESS, email)
        user = await self._user_by_email(email)
        if user is None or not user.is_active or user.email is None:
            return
        raw = await self._new_action_token(
            user,
            ActionTokenPurpose.RESET_PASSWORD,
            dt.timedelta(minutes=self.ctx.settings.password_reset_ttl_minutes),
        )
        audit.record(
            self.db,
            action="auth.password_reset_requested",
            actor_id=user.id,
            target_type="user",
            target_id=user.id,
            ip=client.ip,
        )
        await self.db.commit()
        await self.ctx.mailer.dispatch(
            EmailJob(
                "password_reset",
                user.email,
                user.locale,
                {"minutes": str(self.ctx.settings.password_reset_ttl_minutes)},
                self._reset_link(raw),
            )
        )

    async def confirm_password_reset(self, raw: str, new_password: str, client: ClientInfo) -> None:
        user = await self._consume_action_token(raw, ActionTokenPurpose.RESET_PASSWORD)
        self.ctx.passwords.validate_policy(new_password, email=user.email)
        user.password_hash = await self.ctx.passwords.hash(new_password)
        if user.email_verified_at is None:
            user.email_verified_at = utcnow()  # they just proved control of the mailbox
        await self._revoke_sessions(user.id, "password_reset")
        user.token_version += 1
        audit.record(
            self.db,
            action="auth.password_reset",
            actor_id=user.id,
            target_type="user",
            target_id=user.id,
            ip=client.ip,
        )
        await self.db.commit()
        await self._password_changed_email(user)

    async def change_password(
        self, principal: Principal, current: str, new: str, client: ClientInfo
    ) -> None:
        await self.ctx.limiter.hit(rl.LOGIN_PER_ACCOUNT, str(principal.user.id))
        user = await self.db.get(User, principal.user.id, with_for_update=True)
        assert user is not None
        if not (await self.ctx.passwords.verify(user.password_hash, current)).ok:
            raise InvalidCredentials("Current password is incorrect.")
        self.ctx.passwords.validate_policy(new, email=user.email)
        user.password_hash = await self.ctx.passwords.hash(new)
        await self._revoke_sessions(user.id, "password_change", except_session=principal.session.id)
        audit.record(
            self.db,
            action="auth.password_change",
            actor_id=user.id,
            target_type="user",
            target_id=user.id,
            ip=client.ip,
        )
        await self.db.commit()
        await self._password_changed_email(user)

    async def _password_changed_email(self, user: User) -> None:
        if user.email:
            await self.ctx.mailer.dispatch(
                EmailJob(
                    "password_changed",
                    user.email,
                    user.locale,
                    {},
                    f"{self.ctx.settings.public_web_url}/forgot-password",
                )
            )

    # --- TOTP --------------------------------------------------------------------
    async def totp_setup(self, principal: Principal) -> TotpSetup:
        user = await self.db.get(User, principal.user.id, with_for_update=True)
        assert user is not None
        if user.mfa_enabled:
            raise Conflict(
                "Two-factor authentication is already enabled.", code="mfa_already_enabled"
            )
        secret = totp.new_secret()
        user.totp_secret_encrypted = self.ctx.cipher.encrypt(
            secret, context=b"totp:" + user.id.bytes
        )
        user.totp_last_counter = None
        await self.db.commit()
        return TotpSetup(
            totp.b32(secret),
            totp.provisioning_uri(
                secret, account=user.email or str(user.id), issuer=self.ctx.settings.app_name
            ),
        )

    async def totp_enable(self, principal: Principal, code: str, client: ClientInfo) -> None:
        await self.ctx.limiter.hit(rl.MFA_PER_ACCOUNT, str(principal.user.id))
        user = await self.db.get(User, principal.user.id, with_for_update=True)
        assert user is not None
        if user.mfa_enabled:
            raise Conflict(
                "Two-factor authentication is already enabled.", code="mfa_already_enabled"
            )
        if user.totp_secret_encrypted is None:
            raise Conflict("Start the setup first.", code="mfa_setup_required")
        self._check_totp(user, code, client, action="auth.mfa_enable")
        user.totp_enabled_at = utcnow()
        sess = await self.db.get(AuthSession, principal.session.id)
        if sess is not None:
            sess.mfa_verified = True
        audit.record(
            self.db,
            action="auth.mfa_enabled",
            actor_id=user.id,
            target_type="user",
            target_id=user.id,
            ip=client.ip,
        )
        await self.db.commit()

    async def totp_disable(
        self, principal: Principal, password: str, code: str, client: ClientInfo
    ) -> None:
        await self.ctx.limiter.hit(rl.MFA_PER_ACCOUNT, str(principal.user.id))
        user = await self.db.get(User, principal.user.id, with_for_update=True)
        assert user is not None
        if not user.mfa_enabled:
            raise Conflict("Two-factor authentication is not enabled.", code="mfa_not_enabled")
        if not (await self.ctx.passwords.verify(user.password_hash, password)).ok:
            raise InvalidCredentials("Current password is incorrect.")
        self._check_totp(user, code, client, action="auth.mfa_disable")
        user.totp_enabled_at = None
        user.totp_secret_encrypted = None
        user.totp_last_counter = None
        await self.db.execute(
            update(AuthSession).where(AuthSession.user_id == user.id).values(mfa_verified=False)
        )
        audit.record(
            self.db,
            action="auth.mfa_disabled",
            actor_id=user.id,
            target_type="user",
            target_id=user.id,
            ip=client.ip,
        )
        await self.db.commit()

    # --- Telegram Mini App -----------------------------------------------------------
    async def telegram_webapp_login(self, init_data: str, client: ClientInfo) -> TokenPair:
        """Sign in (or sign up) with the signed `initData` Telegram gives the Mini App.

        Telegram has verified the account, so no email is needed. Staff accounts can't use
        this path: their sessions need TOTP, which only the password login offers."""
        await self.ctx.limiter.hit(rl.LOGIN_PER_IP, client.ip or "unknown")
        tg = validate_init_data(
            init_data,
            self.ctx.settings.telegram_bot_token.get_secret_value(),
            max_age=dt.timedelta(seconds=self.ctx.settings.telegram_webapp_max_age_seconds),
            now=utcnow(),
        )
        user = await self.db.scalar(select(User).where(User.telegram_id == tg.id))
        if user is None:
            user = User(telegram_id=tg.id, locale=normalize(tg.language_code) or "en")
            self.db.add(user)
            try:
                await self.db.flush()
            except IntegrityError:  # two first opens racing
                await self.db.rollback()
                user = await self.db.scalar(select(User).where(User.telegram_id == tg.id))
                assert user is not None
            else:
                audit.record(
                    self.db,
                    action="auth.register",
                    actor_id=user.id,
                    target_type="user",
                    target_id=user.id,
                    ip=client.ip,
                    details={"channel": "telegram"},
                )
        if user.status == UserStatus.SUSPENDED:
            raise AccountSuspended()
        if user.status != UserStatus.ACTIVE or is_staff(user.roles):
            raise NotAuthenticated("This account can't sign in with Telegram.")
        return await self._start_session(
            user, client, mfa_verified=False, action="auth.login_telegram"
        )
