"""Send a service notification to a user over every channel they have: email and/or Telegram."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.i18n import t
from app.notifications.email import EmailJob
from app.notifications.telegram import TelegramJob

if TYPE_CHECKING:
    from app.core.context import AppContext
    from app.models import User


def miniapp_url(ctx: AppContext) -> str:
    return f"{ctx.settings.public_web_url}/app/"


async def notify(
    ctx: AppContext, user: User, template: str, params: dict[str, str], action_url: str
) -> None:
    if not user.is_active:
        return
    if user.email:
        await ctx.mailer.dispatch(EmailJob(template, user.email, user.locale, params, action_url))
    if user.telegram_id:
        p = {"app_name": ctx.settings.app_name, **params}
        text = (
            f"{t(user.locale, f'email.{template}.subject', **p)}\n\n"
            f"{t(user.locale, f'email.{template}.body', **p)}"
        )
        await ctx.telegram.dispatch(
            TelegramJob(
                chat_id=user.telegram_id,
                text=text,
                button_text=t(user.locale, f"email.{template}.action", **p),
                webapp_url=miniapp_url(ctx),
            )
        )
