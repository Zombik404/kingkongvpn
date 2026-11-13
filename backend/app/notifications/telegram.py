"""Telegram messages from the backend (Bot API `sendMessage`), delivered by a Celery task."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict, dataclass
from typing import Any, Protocol

import httpx

from app.core.config import Settings

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class TelegramJob:
    chat_id: int
    text: str
    button_text: str | None = None
    webapp_url: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TelegramJob:
        return cls(
            int(data["chat_id"]), str(data["text"]), data.get("button_text"), data.get("webapp_url")
        )


class TelegramSendError(RuntimeError):
    """Retryable delivery failure."""


def send_sync(job: TelegramJob, settings: Settings, client: httpx.Client | None = None) -> None:
    token = settings.telegram_bot_token.get_secret_value()
    if not token:
        return
    body: dict[str, Any] = {
        "chat_id": job.chat_id,
        "text": job.text[:4000],
        "disable_web_page_preview": True,
    }
    if job.button_text and job.webapp_url:
        body["reply_markup"] = {
            "inline_keyboard": [[{"text": job.button_text, "web_app": {"url": job.webapp_url}}]]
        }
    owns = client is None
    http = client or httpx.Client(timeout=10.0)
    try:
        r = http.post(f"https://api.telegram.org/bot{token}/sendMessage", json=body)
    except httpx.HTTPError as exc:
        raise TelegramSendError(type(exc).__name__) from exc
    finally:
        if owns:
            http.close()
    if r.status_code == 403:  # user blocked the bot: nothing to retry
        log.info("telegram: chat %s blocked the bot", job.chat_id)
        return
    if r.status_code == 429 or r.status_code >= 500:
        raise TelegramSendError(f"status {r.status_code}")
    if r.status_code != 200:
        log.warning("telegram sendMessage failed: %s", r.text[:200])


class TelegramDispatcher(Protocol):
    async def dispatch(self, job: TelegramJob) -> None: ...


class CeleryTelegramDispatcher:
    async def dispatch(self, job: TelegramJob) -> None:
        from app.workers.tasks import send_telegram

        try:
            await asyncio.to_thread(send_telegram.delay, job.to_dict())
        except Exception:
            log.exception("failed to enqueue telegram message")


class MemoryTelegramDispatcher:
    def __init__(self) -> None:
        self.sent: list[TelegramJob] = []

    async def dispatch(self, job: TelegramJob) -> None:
        self.sent.append(job)


class NullTelegramDispatcher:
    async def dispatch(self, job: TelegramJob) -> None:
        return None


def make_telegram_dispatcher(settings: Settings) -> TelegramDispatcher:
    if settings.telegram_delivery == "memory":
        return MemoryTelegramDispatcher()
    if settings.telegram_delivery == "off" or not settings.telegram_bot_token.get_secret_value():
        return NullTelegramDispatcher()
    return CeleryTelegramDispatcher()
