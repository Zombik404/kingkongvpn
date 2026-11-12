"""Access tokens (JWT, EdDSA/Ed25519) and opaque refresh/action tokens (ADR-007)."""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import logging
import secrets
import uuid
from dataclasses import dataclass
from typing import Any, Literal

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from app.core.config import ConfigError, Settings
from app.core.errors import NotAuthenticated

log = logging.getLogger(__name__)

TokenType = Literal["access", "mfa"]


@dataclass(frozen=True)
class AccessClaims:
    sub: uuid.UUID
    sid: uuid.UUID
    roles: tuple[str, ...]
    ver: int
    amr: tuple[str, ...]
    exp: int


@dataclass(frozen=True)
class MfaClaims:
    sub: uuid.UUID
    ver: int
    jti: str


def _load_keys(settings: Settings) -> tuple[Ed25519PrivateKey, Ed25519PublicKey]:
    priv_path, pub_path = settings.jwt_private_key_file, settings.jwt_public_key_file
    if priv_path and pub_path and priv_path.is_file() and pub_path.is_file():
        try:
            priv_pem, pub_pem = priv_path.read_bytes(), pub_path.read_bytes()
        except OSError as exc:
            # Typical cause: key files are 0600 for the host user, the container runs as `app`.
            if not settings.is_dev_like:
                raise ConfigError(f"cannot read JWT key files: {exc}") from exc
            log.warning("JWT key files unreadable (%s); using an ephemeral dev key", exc)
        else:
            priv = serialization.load_pem_private_key(priv_pem, password=None)
            pub = serialization.load_pem_public_key(pub_pem)
            if not isinstance(priv, Ed25519PrivateKey) or not isinstance(pub, Ed25519PublicKey):
                raise ConfigError("JWT keys must be Ed25519")
            return priv, pub
    elif not settings.is_dev_like:
        raise ConfigError("JWT key files are required outside development")
    else:
        log.warning("JWT key files not found; using an ephemeral dev key (dies on restart)")
    key = Ed25519PrivateKey.generate()
    return key, key.public_key()


class TokenService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._private, self._public = _load_keys(settings)
        self._pepper = settings.refresh_token_pepper.get_secret_value().encode()

    # --- JWT ------------------------------------------------------------------
    def _encode(self, payload: dict[str, Any], ttl_seconds: int) -> tuple[str, int]:
        now = int(dt.datetime.now(dt.UTC).timestamp())
        exp = now + ttl_seconds
        body = {
            **payload,
            "iss": self._settings.jwt_issuer,
            "aud": self._settings.jwt_audience,
            "iat": now,
            "nbf": now,
            "exp": exp,
            "jti": secrets.token_urlsafe(12),
        }
        return jwt.encode(body, self._private, algorithm="EdDSA"), exp

    def _decode(self, token: str, expected: TokenType) -> dict[str, Any]:
        try:
            data: dict[str, Any] = jwt.decode(
                token,
                self._public,
                algorithms=["EdDSA"],
                audience=self._settings.jwt_audience,
                issuer=self._settings.jwt_issuer,
                options={"require": ["exp", "iat", "sub", "typ", "jti"]},
                leeway=5,
            )
        except jwt.PyJWTError as exc:
            raise NotAuthenticated("Invalid or expired token.") from exc
        if data.get("typ") != expected:
            raise NotAuthenticated("Invalid or expired token.")
        return data

    def issue_access(
        self,
        *,
        user_id: uuid.UUID,
        session_id: uuid.UUID,
        roles: list[str],
        ver: int,
        amr: list[str],
    ) -> tuple[str, int]:
        return self._encode(
            {
                "typ": "access",
                "sub": str(user_id),
                "sid": str(session_id),
                "roles": roles,
                "ver": ver,
                "amr": amr,
            },
            self._settings.jwt_access_ttl_seconds,
        )

    def decode_access(self, token: str) -> AccessClaims:
        data = self._decode(token, "access")
        try:
            return AccessClaims(
                sub=uuid.UUID(data["sub"]),
                sid=uuid.UUID(data["sid"]),
                roles=tuple(data.get("roles", [])),
                ver=int(data["ver"]),
                amr=tuple(data.get("amr", [])),
                exp=int(data["exp"]),
            )
        except (KeyError, ValueError, TypeError) as exc:
            raise NotAuthenticated("Invalid or expired token.") from exc

    def issue_mfa_challenge(self, *, user_id: uuid.UUID, ver: int) -> str:
        token, _ = self._encode(
            {"typ": "mfa", "sub": str(user_id), "ver": ver},
            self._settings.mfa_challenge_ttl_seconds,
        )
        return token

    def decode_mfa_challenge(self, token: str) -> MfaClaims:
        data = self._decode(token, "mfa")
        try:
            return MfaClaims(sub=uuid.UUID(data["sub"]), ver=int(data["ver"]), jti=data["jti"])
        except (KeyError, ValueError, TypeError) as exc:
            raise NotAuthenticated("Invalid or expired token.") from exc

    # --- Opaque tokens ---------------------------------------------------------
    @staticmethod
    def new_opaque() -> str:
        return secrets.token_urlsafe(32)  # 256 bits

    def hash_opaque(self, token: str) -> bytes:
        return hmac.new(self._pepper, token.encode(), hashlib.sha256).digest()
