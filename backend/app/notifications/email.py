"""Transactional email: render from i18n catalogs, deliver via SMTP (Celery in production)."""

from __future__ import annotations

import asyncio
import logging
import smtplib
import ssl
from dataclasses import asdict, dataclass, field
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path
from typing import Any, Protocol

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from app.core.config import Settings
from app.i18n import normalize, t

log = logging.getLogger(__name__)

TEMPLATES = frozenset(
    {
        "verify_email",
        "account_exists",
        "password_reset",
        "password_changed",
        "subscription_ending",
        "subscription_expired",
        "payment_received",
        "referral_reward",
        "referral_milestone",
        "game_round_away",
        "game_kicked",
        "game_redeem",
        "game_bonus_admin",
        "game_season_reward",
    }
)

_env = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    autoescape=select_autoescape(enabled_extensions=("html.j2",), default=False),
    undefined=StrictUndefined,
    keep_trailing_newline=True,
)


@dataclass(frozen=True)
class EmailJob:
    """Serializable description of an email (what goes through the Celery broker)."""

    template: str
    to: str
    locale: str
    params: dict[str, str] = field(default_factory=dict)
    action_url: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EmailJob:
        return cls(
            template=str(data["template"]),
            to=str(data["to"]),
            locale=str(data["locale"]),
            params={str(k): str(v) for k, v in dict(data.get("params") or {}).items()},
            action_url=data.get("action_url"),
        )


@dataclass(frozen=True)
class RenderedEmail:
    to: str
    subject: str
    text: str
    html: str
    template: str
    action_url: str | None


def render(job: EmailJob, settings: Settings) -> RenderedEmail:
    if job.template not in TEMPLATES:
        raise ValueError(f"unknown email template {job.template!r}")
    locale = normalize(job.locale) or "en"
    params = {"app_name": settings.app_name, **job.params}
    key = f"email.{job.template}"
    ctx = {
        "lang": locale,
        "subject": t(locale, f"{key}.subject", **params),
        "greeting": t(locale, "email.common.greeting", **params),
        "body": t(locale, f"{key}.body", **params),
        "action": t(locale, f"{key}.action", **params) if job.action_url else None,
        "action_url": job.action_url,
        "button_fallback": t(locale, "email.common.button_fallback", **params),
        "footer": t(locale, "email.common.footer", **params),
        "app_name": settings.app_name,
    }
    return RenderedEmail(
        to=job.to,
        subject=ctx["subject"] or "",
        text=_env.get_template("layout.txt.j2").render(**ctx),
        html=_env.get_template("layout.html.j2").render(**ctx),
        template=job.template,
        action_url=job.action_url,
    )


def send_smtp(message: RenderedEmail, settings: Settings) -> None:
    msg = EmailMessage()
    msg["From"] = settings.smtp_from
    msg["To"] = message.to
    msg["Subject"] = message.subject
    msg["Date"] = formatdate(localtime=False)
    msg["Message-ID"] = make_msgid(domain=settings.smtp_from.rpartition("@")[2] or None)
    msg["Auto-Submitted"] = "auto-generated"
    msg.set_content(message.text)
    msg.add_alternative(message.html, subtype="html")
    with smtplib.SMTP(
        settings.smtp_host, settings.smtp_port, timeout=settings.smtp_timeout_seconds
    ) as smtp:
        if settings.smtp_starttls:
            smtp.starttls(context=ssl.create_default_context())
        if settings.smtp_username:
            smtp.login(settings.smtp_username, settings.smtp_password.get_secret_value())
        smtp.send_message(msg)


class EmailDispatcher(Protocol):
    async def dispatch(self, job: EmailJob) -> None: ...


class CeleryDispatcher:
    """Queue for the worker. Failure to enqueue is logged, never fails the user request:
    every email we send has a user-triggered retry path (resend, reset again)."""

    async def dispatch(self, job: EmailJob) -> None:
        from app.workers.tasks import send_email

        try:
            await asyncio.to_thread(send_email.delay, job.to_dict())
        except Exception:
            log.exception("failed to enqueue email %s", job.template)


class SyncSmtpDispatcher:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def dispatch(self, job: EmailJob) -> None:
        try:
            await asyncio.to_thread(send_smtp, render(job, self._settings), self._settings)
        except Exception:
            log.exception("failed to send email %s", job.template)


class MemoryDispatcher:
    """Test double: renders (so templates are exercised) and keeps messages in memory."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self.outbox: list[RenderedEmail] = []

    async def dispatch(self, job: EmailJob) -> None:
        self.outbox.append(render(job, self._settings))


def make_dispatcher(settings: Settings) -> EmailDispatcher:
    if settings.email_delivery == "memory":
        return MemoryDispatcher(settings)
    if settings.email_delivery == "sync":
        return SyncSmtpDispatcher(settings)
    return CeleryDispatcher()
