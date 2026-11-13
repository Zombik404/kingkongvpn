from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot.main import BotConfig, build_dispatcher, lang_of, open_button, start_reply

CFG = BotConfig("123:abc", "https://vpn.example.org/app/", "GlobalVPN")


def test_lang() -> None:
    assert lang_of("ru") == "ru" and lang_of("uk-UA") == "ru" and lang_of("de") == "en"
    assert lang_of(None) == "en"


def test_start_plain_and_with_invite() -> None:
    text, kb = start_reply(CFG, "ru", None)
    assert "GlobalVPN" in text
    btn = kb.inline_keyboard[0][0]
    assert btn.web_app is not None and btn.web_app.url == "https://vpn.example.org/app/"
    text, kb = start_reply(CFG, "en", "inv-ab2c-xy34")
    assert "INV-AB2C-XY34" in text
    assert kb.inline_keyboard[0][0].web_app.url.endswith("/app/?invite=INV-AB2C-XY34")
    # anything that isn't an invite code is ignored (no injection into the URL)
    _, kb = start_reply(CFG, "en", "INV-AB2C-XY34&x=<script>")
    assert kb.inline_keyboard[0][0].web_app.url == "https://vpn.example.org/app/"


def test_open_button_keeps_existing_query() -> None:
    cfg = BotConfig("t", "https://vpn.example.org/app/?v=2", "X")
    assert (
        open_button(cfg, "en", "INV-AAAA-BBBB")
        .inline_keyboard[0][0]
        .web_app.url.endswith("?v=2&invite=INV-AAAA-BBBB")
    )


def test_config_requires_https(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("MINIAPP_URL", "http://insecure/app/")
    with pytest.raises(ValueError):
        BotConfig.from_env()
    monkeypatch.setenv("MINIAPP_URL", "https://ok.example/app/")
    assert BotConfig.from_env().miniapp_url == "https://ok.example/app/"


def test_dispatcher_builds() -> None:
    dp = build_dispatcher(CFG)
    assert len(dp.message.handlers) == 3


def test_referral_deep_link() -> None:
    text, kb = start_reply(CFG, "ru", "ref_AB23CD45")
    assert "пригласили" in text
    assert kb.inline_keyboard[0][0].web_app.url.endswith("/app/?ref=AB23CD45")
    _, kb = start_reply(CFG, "en", "ref_bad")
    assert kb.inline_keyboard[0][0].web_app.url == "https://vpn.example.org/app/"
