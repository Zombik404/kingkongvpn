"""Async SQLAlchemy engine and session factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.core.config import Settings


def make_engine(settings: Settings, *, null_pool: bool = False) -> AsyncEngine:
    kwargs: dict[str, Any] = {"pool_pre_ping": True}
    if null_pool:
        kwargs["poolclass"] = NullPool
    else:
        kwargs["pool_size"] = settings.db_pool_size
        kwargs["max_overflow"] = settings.db_max_overflow
    return create_async_engine(settings.database_url, **kwargs)


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


async def session_scope(factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    async with factory() as session:
        try:
            yield session
        except BaseException:
            await session.rollback()
            raise


def violated_constraint(exc: IntegrityError) -> str | None:
    """Name of the violated constraint from an asyncpg-backed IntegrityError, if known."""
    candidates: list[object] = [exc.orig, getattr(exc.orig, "__cause__", None)]
    for obj in candidates:
        name = getattr(obj, "constraint_name", None)
        if isinstance(name, str):
            return name
    return None
