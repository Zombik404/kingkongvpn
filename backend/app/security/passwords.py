"""Argon2id password hashing (ADR-007). Parameters are embedded in each hash string,
so raising them later only needs `needs_rehash` on the next successful login."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import Settings
from app.core.errors import AppError

MAX_PASSWORD_LENGTH = 256  # bound hashing cost and request size


class WeakPassword(AppError):
    status_code = 422
    code = "weak_password"


@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    needs_rehash: bool = False


class PasswordService:
    def __init__(self, settings: Settings) -> None:
        self._min_length = settings.password_min_length
        if settings.password_hash_profile == "fast-insecure-for-tests":  # noqa: S105
            self._hasher = PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1)
        else:
            # RFC 9106 second recommended option: t=3, m=64 MiB, p=4.
            self._hasher = PasswordHasher(time_cost=3, memory_cost=64 * 1024, parallelism=4)
        # Hash compared against when the account doesn't exist, so response time
        # doesn't reveal whether an email is registered.
        self._dummy_hash = self._hasher.hash("dummy-password-for-timing")

    def validate_policy(self, password: str, *, email: str | None = None) -> None:
        if len(password) < self._min_length:
            raise WeakPassword(f"Password must be at least {self._min_length} characters.")
        if len(password) > MAX_PASSWORD_LENGTH:
            raise WeakPassword(f"Password must be at most {MAX_PASSWORD_LENGTH} characters.")
        if len(set(password)) < 4:
            raise WeakPassword("Password is too simple.")
        if email and password.casefold() == email.casefold():
            raise WeakPassword("Password must not be your email address.")

    def hash_sync(self, password: str) -> str:
        return self._hasher.hash(password)

    def verify_sync(self, password_hash: str | None, password: str) -> VerifyResult:
        target = password_hash or self._dummy_hash
        try:
            self._hasher.verify(target, password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return VerifyResult(ok=False)
        if password_hash is None:
            return VerifyResult(ok=False)
        return VerifyResult(ok=True, needs_rehash=self._hasher.check_needs_rehash(password_hash))

    # Hashing is CPU-bound (~50-100 ms); keep it off the event loop.
    async def hash(self, password: str) -> str:
        return await asyncio.to_thread(self.hash_sync, password)

    async def verify(self, password_hash: str | None, password: str) -> VerifyResult:
        return await asyncio.to_thread(self.verify_sync, password_hash, password)
