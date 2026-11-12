"""Message catalogs (ADR-013) and locale negotiation.

Catalogs live in `app/i18n/locales/<lang>.json`. Placeholders use `{name}` syntax.
Missing keys fall back to English, then to the key itself (never crash a send).
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any

from app.core.config import DEFAULT_LOCALE, SUPPORTED_LOCALES

_DIR = Path(__file__).parent / "locales"


@cache
def catalog(locale: str) -> dict[str, Any]:
    path = _DIR / f"{locale}.json"
    if locale not in SUPPORTED_LOCALES or not path.is_file():
        return {}
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def _lookup(data: dict[str, Any], key: str) -> str | None:
    node: Any = data
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node if isinstance(node, str) else None


class _SafeDict(dict[str, str]):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def t(locale: str, key: str, **params: object) -> str:
    text = _lookup(catalog(locale), key) or _lookup(catalog(DEFAULT_LOCALE), key) or key
    return text.format_map(_SafeDict({k: str(v) for k, v in params.items()}))


def normalize(locale: str | None) -> str | None:
    if not locale:
        return None
    base = locale.strip().replace("_", "-").split("-")[0].lower()
    return base if base in SUPPORTED_LOCALES else None


def negotiate(explicit: str | None = None, accept_language: str | None = None) -> str:
    """User setting → Accept-Language (q-ordered) → default."""
    if chosen := normalize(explicit):
        return chosen
    if accept_language:
        weighted: list[tuple[float, int, str]] = []
        for i, part in enumerate(accept_language.split(",")[:20]):
            lang, _, params = part.strip().partition(";")
            q = 1.0
            if params.strip().startswith("q="):
                try:
                    q = float(params.strip()[2:])
                except ValueError:
                    q = 0.0
            weighted.append((-q, i, lang))
        for neg_q, _, lang in sorted(weighted):
            if neg_q < 0 and (chosen := normalize(lang)):
                return chosen
    return DEFAULT_LOCALE
