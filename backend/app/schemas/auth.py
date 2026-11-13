from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

Password = Field(min_length=1, max_length=256)
OpaqueToken = Field(min_length=16, max_length=128)


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)


class RegisterIn(_In):
    email: EmailStr = Field(max_length=254)
    password: str = Password
    locale: str | None = Field(default=None, max_length=8)


class EmailIn(_In):
    email: EmailStr = Field(max_length=254)


class TokenIn(_In):
    token: str = OpaqueToken


class LoginIn(_In):
    email: EmailStr = Field(max_length=254)
    password: str = Password


class MfaVerifyIn(_In):
    mfa_token: str = Field(min_length=16, max_length=2048)
    code: str = Field(min_length=6, max_length=10)


class TelegramLoginIn(_In):
    init_data: str = Field(min_length=10, max_length=8192)


class RefreshIn(_In):
    refresh_token: str = OpaqueToken


class PasswordResetConfirmIn(_In):
    token: str = OpaqueToken
    new_password: str = Password


class PasswordChangeIn(_In):
    current_password: str = Password
    new_password: str = Password


class TotpCodeIn(_In):
    code: str = Field(min_length=6, max_length=10)


class TotpDisableIn(_In):
    password: str = Password
    code: str = Field(min_length=6, max_length=10)


class TokenPairOut(BaseModel):
    token_type: Literal["bearer"] = "bearer"  # noqa: S105
    access_token: str
    refresh_token: str
    expires_in: int
    session_id: uuid.UUID


class MfaChallengeOut(BaseModel):
    mfa_required: Literal[True] = True
    mfa_token: str


class TotpSetupOut(BaseModel):
    secret: str
    otpauth_uri: str


class AcceptedOut(BaseModel):
    status: Literal["accepted"] = "accepted"
    detail: str
