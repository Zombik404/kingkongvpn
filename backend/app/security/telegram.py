"""Telegram Mini App `initData` validation.

https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
secret_key = HMAC_SHA256(key="WebAppData", msg=bot_token)
hash       = hex(HMAC_SHA256(key=secret_key, msg=data_check_string))
data_check_string = all fields except `hash`, sorted by key, "key=value" joined with "\n".
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
from dataclasses import dataclass
from urllib.parse import parse_qsl

from app.core.errors import NotAuthenticated


@dataclass(frozen=True)
class TelegramUser:
    id: int
    first_name: str | None
    username: str | None
    language_code: str | None
    is_bot: bool


def _secret(bot_token: str) -> bytes:
    return hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()


def sign_init_data(fields: dict[str, str], bot_token: str) -> str:
    """Build a signed initData string (used by tests and local tooling)."""
    from urllib.parse import urlencode

    check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    digest = hmac.new(_secret(bot_token), check.encode(), hashlib.sha256).hexdigest()
    return urlencode({**fields, "hash": digest})


def validate_init_data(
    init_data: str, bot_token: str, *, max_age: dt.timedelta, now: dt.datetime
) -> TelegramUser:
    invalid = NotAuthenticated("Telegram sign-in data is invalid or expired.")
    if not bot_token or not init_data or len(init_data) > 8192:
        raise invalid
    pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=False)
    fields: dict[str, str] = {}
    for key, value in pairs:
        if key in fields:  # duplicate keys make the check string ambiguous
            raise invalid
        fields[key] = value
    received = fields.pop("hash", "")
    check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    expected = hmac.new(_secret(bot_token), check.encode(), hashlib.sha256).hexdigest()
    if not received or not hmac.compare_digest(expected, received.lower()):
        raise invalid
    try:
        auth_date = dt.datetime.fromtimestamp(int(fields["auth_date"]), tz=dt.UTC)
        user = json.loads(fields["user"])
        tg = TelegramUser(
            id=int(user["id"]),
            first_name=user.get("first_name"),
            username=user.get("username"),
            language_code=user.get("language_code"),
            is_bot=bool(user.get("is_bot", False)),
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise invalid from exc
    if now - auth_date > max_age or auth_date - now > dt.timedelta(minutes=5) or tg.is_bot:
        raise invalid
    return tg
