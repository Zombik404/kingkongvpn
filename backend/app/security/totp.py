"""RFC 6238 TOTP (SHA-1, 6 digits, 30 s) — the variant every authenticator app supports."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote, urlencode

PERIOD = 30
DIGITS = 6


def new_secret() -> bytes:
    return secrets.token_bytes(20)


def b32(secret: bytes) -> str:
    return base64.b32encode(secret).decode().rstrip("=")


def code_at(secret: bytes, counter: int) -> str:
    digest = hmac.new(secret, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10**DIGITS).zfill(DIGITS)


def current_counter(now: float | None = None) -> int:
    return int((time.time() if now is None else now) // PERIOD)


def verify(
    secret: bytes,
    code: str,
    *,
    now: float | None = None,
    window: int = 1,
    last_counter: int | None = None,
) -> int | None:
    """Return the matched counter, or None. Counters <= last_counter are rejected (no replay)."""
    code = code.strip().replace(" ", "")
    if len(code) != DIGITS or not code.isdigit():
        return None
    base = current_counter(now)
    for counter in range(base - window, base + window + 1):
        if last_counter is not None and counter <= last_counter:
            continue
        if hmac.compare_digest(code_at(secret, counter), code):
            return counter
    return None


def provisioning_uri(secret: bytes, *, account: str, issuer: str) -> str:
    label = quote(f"{issuer}:{account}")
    query = urlencode(
        {
            "secret": b32(secret),
            "issuer": issuer,
            "algorithm": "SHA1",
            "digits": DIGITS,
            "period": PERIOD,
        }
    )
    return f"otpauth://totp/{label}?{query}"
