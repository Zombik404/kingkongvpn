"""Redis sliding-window rate limiter. Identifiers are hashed so no emails/IPs sit in Redis."""

from __future__ import annotations

import hashlib
import logging
import secrets
import time
from dataclasses import dataclass

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.errors import RateLimited

log = logging.getLogger(__name__)

_SCRIPT = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
redis.call('ZREMRANGEBYSCORE', key, 0, now - window)
local count = redis.call('ZCARD', key)
if count >= limit then
  local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
  return {0, tonumber(oldest[2]) + window - now}
end
redis.call('ZADD', key, now, ARGV[4])
redis.call('PEXPIRE', key, window)
return {1, 0}
"""


@dataclass(frozen=True)
class Limit:
    name: str
    limit: int
    window_seconds: int


# Central catalogue so limits are reviewable in one place.
LOGIN_PER_IP = Limit("login-ip", 20, 60)
LOGIN_PER_ACCOUNT = Limit("login-acct", 10, 15 * 60)
REGISTER_PER_IP = Limit("register-ip", 5, 60 * 60)
EMAIL_PER_ADDRESS = Limit("email-addr", 3, 60 * 60)  # verification resend / reset requests
EMAIL_PER_IP = Limit("email-ip", 20, 60 * 60)
REFRESH_PER_IP = Limit("refresh-ip", 60, 60)
MFA_PER_ACCOUNT = Limit("mfa-acct", 10, 15 * 60)
PROMO_PER_ACCOUNT = Limit("promo-acct", 10, 60 * 60)
# Each new device takes a tunnel address until it is revoked and released, so a register/revoke
# loop could otherwise drain the pool.
DEVICE_REGISTER_PER_ACCOUNT = Limit("device-reg", 10, 24 * 60 * 60)
# Every connect may move the peer between nodes (revision bumps on both).
CONNECT_PER_ACCOUNT = Limit("vpn-connect", 30, 10 * 60)
EXPORT_PER_ACCOUNT = Limit("export", 5, 60 * 60)


class RateLimiter:
    def __init__(self, redis: Redis, *, enabled: bool = True, prefix: str = "rl") -> None:
        self._redis = redis
        self._enabled = enabled
        self._prefix = prefix
        self._script = redis.register_script(_SCRIPT)

    def _key(self, limit: Limit, identifier: str) -> str:
        digest = hashlib.sha256(identifier.casefold().encode()).hexdigest()[:32]
        return f"{self._prefix}:{limit.name}:{digest}"

    async def hit(self, limit: Limit, identifier: str) -> None:
        """Record an attempt; raise RateLimited if over the limit.

        Fails open on Redis errors (logged): a cache outage shouldn't lock every user
        out. Argon2 cost and generic errors still slow down brute force meanwhile.
        """
        if not self._enabled:
            return
        now_ms = int(time.time() * 1000)
        try:
            allowed, retry_ms = await self._script(
                keys=[self._key(limit, identifier)],
                args=[
                    now_ms,
                    limit.window_seconds * 1000,
                    limit.limit,
                    f"{now_ms}-{secrets.token_hex(4)}",
                ],
            )
        except RedisError:
            log.exception("rate limiter unavailable; failing open for %s", limit.name)
            return
        if not int(allowed):
            retry_after = max(1, int(retry_ms) // 1000 + 1)
            raise RateLimited(headers={"Retry-After": str(retry_after)})

    async def reset(self, limit: Limit, identifier: str) -> None:
        if not self._enabled:
            return
        try:
            await self._redis.delete(self._key(limit, identifier))
        except RedisError:
            log.exception("rate limiter reset failed")
