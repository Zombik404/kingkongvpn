"""Telegram bot (aiogram 3, long polling).

The bot is deliberately thin: everything (account, invite, payment, devices) happens in the
Mini App, which signs in with Telegram's signed initData. The bot never sees VPN keys or
configs (ADR-003). Service notifications are sent by the backend directly.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import dataclass
from urllib.parse import quote

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    MenuButtonWebApp,
    Message,
    WebAppInfo,
)

log = logging.getLogger("globalvpn.bot")
INVITE_RE = re.compile(r"^INV-[A-Z0-9]{4}-[A-Z0-9]{4}$")
REF_RE = re.compile(r"^REF_([A-Z0-9]{8})$")

TEXT = {
    "ru": {
        "hello": "Привет! Это {app} — VPN прямо в Telegram.\n\n"
        "Нажмите «Открыть VPN»: там можно активировать доступ, оплатить и подключить устройство.",
        "hello_invite": "Привет! Ваш инвайт-код {code} уже подставлен — нажмите «Открыть VPN» "
        "и затем «Активировать».",
        "hello_ref": "Привет! Вас пригласили в {app}. Нажмите «Открыть VPN», чтобы начать.",
        "open": "Открыть VPN",
        "help": "Как подключиться:\n"
        "1. Установите приложение WireGuard (Android, iPhone, Windows, macOS).\n"
        "2. Откройте VPN по кнопке ниже → «Добавить устройство».\n"
        "3. Сохраните конфигурацию (файл или QR-код) и импортируйте её в WireGuard.\n\n"
        "Ключ создаётся на вашем устройстве и не хранится у нас, поэтому сохраните "
        "конфигурацию сразу. Потеряли — просто создайте новое подключение.",
        "other": "Всё управление — в приложении:",
        "menu": "VpnHub",
    },
    "en": {
        "hello": "Hi! This is {app} — a VPN right inside Telegram.\n\n"
        "Tap “Open VPN” to activate access, pay and connect your devices.",
        "hello_invite": "Hi! Your invite code {code} is already filled in — tap “Open VPN”, "
        "then “Activate”.",
        "hello_ref": "Hi! You've been invited to {app}. Tap “Open VPN” to get started.",
        "open": "Open VPN",
        "help": "How to connect:\n"
        "1. Install the WireGuard app (Android, iPhone, Windows, macOS).\n"
        "2. Open the VPN with the button below → “Add device”.\n"
        "3. Save the configuration (file or QR code) and import it into WireGuard.\n\n"
        "The key is created on your device and isn't stored by us, so save the configuration "
        "right away. Lost it? Just create a new connection.",
        "other": "Everything is managed in the app:",
        "menu": "VpnHub",
    },
}


@dataclass(frozen=True)
class BotConfig:
    token: str
    miniapp_url: str
    app_name: str

    @classmethod
    def from_env(cls) -> BotConfig:
        url = os.environ["MINIAPP_URL"].strip()
        if not url.startswith("https://"):
            raise ValueError("MINIAPP_URL must be https:// (Telegram requires it)")
        return cls(
            os.environ["TELEGRAM_BOT_TOKEN"].strip(), url, os.environ.get("APP_NAME", "VpnHub")
        )


def lang_of(code: str | None) -> str:
    c = (code or "").lower()
    return "ru" if c.startswith(("ru", "uk", "be")) else "en"


def open_button(
    cfg: BotConfig, lang: str, invite: str | None = None, ref: str | None = None
) -> InlineKeyboardMarkup:
    url = cfg.miniapp_url
    for key, value in (("invite", invite), ("ref", ref)):
        if value:
            url += ("&" if "?" in url else "?") + f"{key}=" + quote(value)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=TEXT[lang]["open"], web_app=WebAppInfo(url=url))]
        ]
    )


def start_reply(cfg: BotConfig, lang: str, payload: str | None) -> tuple[str, InlineKeyboardMarkup]:
    invite = (payload or "").strip().upper()
    if INVITE_RE.match(invite):
        return TEXT[lang]["hello_invite"].format(code=invite), open_button(cfg, lang, invite)
    if m := REF_RE.match(invite):
        return TEXT[lang]["hello_ref"].format(app=cfg.app_name), open_button(cfg, lang, ref=m[1])
    return TEXT[lang]["hello"].format(app=cfg.app_name), open_button(cfg, lang)


def build_dispatcher(cfg: BotConfig) -> Dispatcher:
    dp = Dispatcher()

    @dp.message(CommandStart())
    async def on_start(message: Message, command: CommandObject) -> None:
        lang = lang_of(message.from_user.language_code if message.from_user else None)
        text, kb = start_reply(cfg, lang, command.args)
        await message.answer(text, reply_markup=kb)

    @dp.message(Command("help"))
    async def on_help(message: Message) -> None:
        lang = lang_of(message.from_user.language_code if message.from_user else None)
        await message.answer(TEXT[lang]["help"], reply_markup=open_button(cfg, lang))

    @dp.message(F.text)
    async def on_other(message: Message) -> None:
        lang = lang_of(message.from_user.language_code if message.from_user else None)
        await message.answer(TEXT[lang]["other"], reply_markup=open_button(cfg, lang))

    return dp


async def configure(bot: Bot, cfg: BotConfig) -> None:
    for lang in ("ru", "en"):
        await bot.set_my_commands(
            [
                BotCommand(command="start", description=TEXT[lang]["open"]),
                BotCommand(command="help", description="Help" if lang == "en" else "Помощь"),
            ],
            language_code=lang,
        )
    await bot.set_chat_menu_button(
        menu_button=MenuButtonWebApp(
            text=TEXT["en"]["menu"], web_app=WebAppInfo(url=cfg.miniapp_url)
        )
    )


async def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    cfg = BotConfig.from_env()
    bot = Bot(cfg.token)
    await configure(bot, cfg)
    log.info("bot started; mini app at %s", cfg.miniapp_url)
    await build_dispatcher(cfg).start_polling(bot, allowed_updates=["message"])


if __name__ == "__main__":
    asyncio.run(run())
