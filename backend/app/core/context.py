"""Process-wide resources, created once at startup (API lifespan or worker task)."""

from __future__ import annotations

from dataclasses import dataclass

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.db import make_engine, make_sessionmaker
from app.notifications.email import EmailDispatcher, make_dispatcher
from app.payments.cryptobot import CryptoBotClient
from app.security.crypto import FieldCipher
from app.security.passwords import PasswordService
from app.security.rate_limit import RateLimiter
from app.security.tokens import TokenService
from app.vpn.allocator import AddressPool


@dataclass
class AppContext:
    settings: Settings
    engine: AsyncEngine
    sessionmaker: async_sessionmaker[AsyncSession]
    redis: Redis
    passwords: PasswordService
    tokens: TokenService
    cipher: FieldCipher
    limiter: RateLimiter
    mailer: EmailDispatcher
    address_pool: AddressPool
    cryptobot: CryptoBotClient | None = None

    @classmethod
    def create(
        cls,
        settings: Settings,
        *,
        mailer: EmailDispatcher | None = None,
        null_pool: bool = False,
        cryptobot: CryptoBotClient | None = None,
    ) -> AppContext:
        engine = make_engine(settings, null_pool=null_pool)
        redis = Redis.from_url(settings.redis_url, decode_responses=False)
        return cls(
            settings=settings,
            engine=engine,
            sessionmaker=make_sessionmaker(engine),
            redis=redis,
            passwords=PasswordService(settings),
            tokens=TokenService(settings),
            cipher=FieldCipher(settings),
            limiter=RateLimiter(redis, enabled=settings.rate_limit_enabled),
            mailer=mailer or make_dispatcher(settings),
            address_pool=AddressPool.from_settings(settings),
            cryptobot=cryptobot
            or (CryptoBotClient(settings) if settings.cryptobot_enabled else None),
        )

    async def close(self) -> None:
        if self.cryptobot is not None:
            await self.cryptobot.aclose()
        await self.redis.aclose()
        await self.engine.dispose()
