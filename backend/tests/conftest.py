"""Test harness: real PostgreSQL + Redis (from docker compose, or CI services).

Defaults match `docker compose up` (the `globalvpn_test` DB is created by the Postgres init
script). Override with TEST_DATABASE_URL / TEST_REDIS_URL.
"""

from __future__ import annotations

import os
import re
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

TEST_DB = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://globalvpn:change-me-dev-only@127.0.0.1:5432/globalvpn_test",
)
TEST_REDIS = os.environ.get("TEST_REDIS_URL", "redis://127.0.0.1:6379/15")

os.environ.update(
    {
        "APP_ENV": "testing",
        "DATABASE_URL": TEST_DB,
        "REDIS_URL": TEST_REDIS,
        "CELERY_BROKER_URL": "memory://",
        "CELERY_RESULT_BACKEND": "cache+memory://",
        "EMAIL_DELIVERY": "memory",
        "PASSWORD_HASH_PROFILE": "fast-insecure-for-tests",
        "REFRESH_TOKEN_PEPPER": "test-pepper-" + "x" * 40,
        "PUBLIC_WEB_URL": "https://web.test",
    }
)
for _var in ("JWT_PRIVATE_KEY_FILE", "JWT_PUBLIC_KEY_FILE", "DATA_ENCRYPTION_KEY"):
    os.environ.pop(_var, None)

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.core.config import Settings  # noqa: E402
from app.core.context import AppContext  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models import Base  # noqa: E402
from app.notifications.email import MemoryDispatcher  # noqa: E402

BACKEND = Path(__file__).resolve().parent.parent


def alembic_config(url: str) -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    cfg.attributes["url"] = url
    cfg.attributes["configure_logger"] = False
    return cfg


@pytest.fixture(scope="session", autouse=True)
def _schema() -> Iterator[None]:
    cfg = alembic_config(TEST_DB)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    yield


def make_settings(**overrides: Any) -> Settings:
    return Settings(**overrides)


@pytest.fixture
def settings() -> Settings:
    return make_settings()


@pytest.fixture
async def ctx(settings: Settings) -> AsyncIterator[AppContext]:
    context = AppContext.create(settings, mailer=MemoryDispatcher(settings), null_pool=True)
    tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    async with context.engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
        await conn.execute(text("ALTER SEQUENCE tunnel_address_seq RESTART WITH 1"))
    await context.redis.flushdb()
    yield context
    await context.close()


@pytest.fixture
def outbox(ctx: AppContext) -> list[Any]:
    assert isinstance(ctx.mailer, MemoryDispatcher)
    return ctx.mailer.outbox


@pytest.fixture
async def client(ctx: AppContext) -> AsyncIterator[AsyncClient]:
    app = create_app(ctx.settings, ctx=ctx)
    transport = ASGITransport(app=app, client=("203.0.113.10", 51000))
    async with AsyncClient(transport=transport, base_url="http://api.test") as http:
        yield http


@pytest.fixture
async def db(ctx: AppContext) -> AsyncIterator[Any]:
    async with ctx.sessionmaker() as session:
        yield session


_TOKEN_RE = re.compile(r"token=([A-Za-z0-9_\-]+)")


def token_from(email: Any) -> str:
    match = _TOKEN_RE.search(email.action_url or "")
    assert match, f"no token in {email.action_url!r}"
    return match.group(1)
