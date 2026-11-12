"""Field-level encryption for small secrets at rest (TOTP seeds). AES-256-GCM."""

from __future__ import annotations

import base64
import binascii
import hashlib
import logging
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import ConfigError, Settings

log = logging.getLogger(__name__)
_VERSION = b"\x01"


class FieldCipher:
    def __init__(self, settings: Settings) -> None:
        raw = (
            settings.data_encryption_key.get_secret_value() if settings.data_encryption_key else ""
        )
        if raw:
            try:
                key = base64.b64decode(raw, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise ConfigError("DATA_ENCRYPTION_KEY must be base64") from exc
            if len(key) != 32:
                raise ConfigError("DATA_ENCRYPTION_KEY must decode to 32 bytes")
        elif settings.is_dev_like:
            log.warning("DATA_ENCRYPTION_KEY not set; deriving a dev-only key from the pepper")
            pepper = settings.refresh_token_pepper.get_secret_value().encode()
            key = hashlib.sha256(b"dev-only-field-key:" + pepper).digest()
        else:
            raise ConfigError("DATA_ENCRYPTION_KEY is required")
        self._aead = AESGCM(key)

    def encrypt(self, plaintext: bytes, *, context: bytes) -> bytes:
        nonce = os.urandom(12)
        return _VERSION + nonce + self._aead.encrypt(nonce, plaintext, context)

    def decrypt(self, blob: bytes, *, context: bytes) -> bytes:
        if not blob or blob[:1] != _VERSION:
            raise ValueError("unknown ciphertext version")
        return self._aead.decrypt(blob[1:13], blob[13:], context)
