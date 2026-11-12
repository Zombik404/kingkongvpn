"""Application settings.

All configuration comes from environment variables (see `.env.example`). Outside
`development`/`testing` the app refuses to start when a required secret is missing
or still holds a placeholder value, so a misconfigured deployment fails loudly at
boot instead of running with weak defaults.
"""

from __future__ import annotations

import ipaddress
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

Environment = Literal["development", "testing", "staging", "production"]
EmailDelivery = Literal["celery", "sync", "memory"]

SUPPORTED_LOCALES: tuple[str, ...] = ("en", "de", "hu", "uk", "ru")
DEFAULT_LOCALE = "en"

_PLACEHOLDERS = frozenset(
    {
        "",
        "change-me-dev-only",
        "replace-with-64-random-hex-chars",
    }
)


class ConfigError(RuntimeError):
    """Raised when settings are unsafe for the selected environment."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", case_sensitive=False, populate_by_name=True)

    # --- General -------------------------------------------------------------
    app_env: Environment = "development"
    app_name: str = "GlobalVPN"
    log_level: str = "INFO"
    public_web_url: str = "http://localhost:3000"
    public_api_url: str = "http://localhost:8000"
    admin_web_url: str = "http://localhost:3001"
    cors_allowed_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://localhost:3001"]
    )

    # --- PostgreSQL ----------------------------------------------------------
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_db: str = "globalvpn"
    postgres_user: str = "globalvpn"
    postgres_password: SecretStr = SecretStr("change-me-dev-only")
    database_url_override: str | None = Field(default=None, alias="DATABASE_URL")
    db_pool_size: int = 10
    db_max_overflow: int = 10

    # --- Redis / Celery ------------------------------------------------------
    redis_url: str = "redis://redis:6379/0"
    celery_broker_url: str = "redis://redis:6379/1"
    celery_result_backend: str = "redis://redis:6379/2"

    # --- Auth / tokens -------------------------------------------------------
    jwt_private_key_file: Path | None = None
    jwt_public_key_file: Path | None = None
    jwt_issuer: str = "globalvpn"
    jwt_audience: str = "globalvpn-api"
    jwt_access_ttl_seconds: int = Field(default=900, ge=60, le=3600)
    mfa_challenge_ttl_seconds: int = Field(default=300, ge=60, le=900)
    refresh_token_ttl_days: int = Field(default=30, ge=1, le=365)
    refresh_token_pepper: SecretStr = SecretStr("replace-with-64-random-hex-chars")
    data_encryption_key: SecretStr | None = None  # base64, 32 bytes; encrypts TOTP secrets
    password_min_length: int = Field(default=10, ge=8, le=64)
    password_hash_profile: Literal["default", "fast-insecure-for-tests"] = "default"  # noqa: S105
    email_token_ttl_hours: int = Field(default=24, ge=1, le=168)
    password_reset_ttl_minutes: int = Field(default=30, ge=5, le=240)
    admin_require_mfa: bool = True
    rate_limit_enabled: bool = True

    # --- Email ---------------------------------------------------------------
    email_delivery: EmailDelivery = "celery"
    smtp_host: str = "mailpit"
    smtp_port: int = 1025
    smtp_username: str = ""
    smtp_password: SecretStr = SecretStr("")
    smtp_from: str = "no-reply@example.invalid"
    smtp_starttls: bool = False
    smtp_timeout_seconds: float = 10.0

    # --- VPN control plane ---------------------------------------------------
    vpn_tunnel_ipv4_pool: ipaddress.IPv4Network = ipaddress.IPv4Network("10.64.0.0/10")
    vpn_tunnel_ipv6_pool: ipaddress.IPv6Network = ipaddress.IPv6Network("fd00:6476:706e::/48")
    vpn_tunnel_reserved_addresses: int = Field(default=16, ge=2)
    node_ca_cert_file: Path | None = None
    node_ca_key_file: Path | None = None
    node_heartbeat_stale_seconds: int = 90
    peer_idle_ttl_hours: int = 24

    # --- Telegram (Phase 5) --------------------------------------------------
    telegram_bot_token: SecretStr = SecretStr("")
    bot_service_client_id: str = "telegram-bot"
    bot_service_client_secret: SecretStr = SecretStr("")

    telegram_bot_username: str = ""  # without '@'; used for "Return to bot" buttons

    # --- Payments: Crypto Pay API (@CryptoBot) -------------------------------
    cryptobot_api_token: SecretStr = SecretStr("")
    cryptobot_network: Literal["mainnet", "testnet"] = "testnet"
    cryptobot_api_url: str | None = None  # override; default derived from network
    # Asset codes accepted for USD-priced invoices. TON was rebranded to Gram — run
    # `python -m app.cli cryptobot-check` to see which code the API currently uses.
    cryptobot_accepted_assets: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["TON"]
    )
    cryptobot_invoice_ttl_seconds: int = Field(default=3600, ge=300, le=86400)
    payment_pending_limit_per_user: int = Field(default=5, ge=1, le=50)

    # --- Observability -------------------------------------------------------
    prometheus_metrics_enabled: bool = True

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [o.strip() for o in value.split(",") if o.strip()]
        return value

    @field_validator("cryptobot_accepted_assets", mode="before")
    @classmethod
    def _split_assets(cls, value: object) -> object:
        if isinstance(value, str):
            return [a.strip().upper() for a in value.split(",") if a.strip()]
        return value

    @field_validator("public_web_url", "public_api_url", "admin_web_url")
    @classmethod
    def _strip_slash(cls, value: str) -> str:
        return value.rstrip("/")

    @model_validator(mode="after")
    def _check_pools(self) -> Settings:
        if self.vpn_tunnel_reserved_addresses >= self.vpn_tunnel_ipv4_pool.num_addresses - 1:
            raise ValueError("VPN_TUNNEL_RESERVED_ADDRESSES leaves no usable addresses in the pool")
        return self

    # ------------------------------------------------------------------------
    @property
    def is_dev_like(self) -> bool:
        return self.app_env in ("development", "testing")

    @property
    def database_url(self) -> str:
        if self.database_url_override:
            return self.database_url_override
        pw = self.postgres_password.get_secret_value()
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{pw}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def cryptobot_base_url(self) -> str:
        if self.cryptobot_api_url:
            return self.cryptobot_api_url.rstrip("/")
        host = "pay.crypt.bot" if self.cryptobot_network == "mainnet" else "testnet-pay.crypt.bot"
        return f"https://{host}/api"

    @property
    def cryptobot_enabled(self) -> bool:
        return bool(self.cryptobot_api_token.get_secret_value())

    def assert_safe_for_environment(self) -> None:
        """Fail fast on missing/placeholder secrets outside development and testing."""
        if self.is_dev_like:
            return
        problems: list[str] = []
        if (
            self.postgres_password.get_secret_value() in _PLACEHOLDERS
            and not self.database_url_override
        ):
            problems.append("POSTGRES_PASSWORD is a placeholder")
        pepper = self.refresh_token_pepper.get_secret_value()
        if pepper in _PLACEHOLDERS or len(pepper) < 32:
            problems.append("REFRESH_TOKEN_PEPPER must be set to at least 32 random characters")
        if self.data_encryption_key is None or not self.data_encryption_key.get_secret_value():
            problems.append("DATA_ENCRYPTION_KEY is required")
        for name in ("jwt_private_key_file", "jwt_public_key_file"):
            path = getattr(self, name)
            if path is None or not Path(path).is_file():
                problems.append(f"{name.upper()} must point to an existing file")
        if self.password_hash_profile != "default":  # noqa: S105
            problems.append("PASSWORD_HASH_PROFILE must be 'default'")
        if self.email_delivery == "memory":
            problems.append("EMAIL_DELIVERY=memory is for tests only")
        if (
            self.app_env == "production"
            and self.cryptobot_enabled
            and (self.cryptobot_network != "mainnet")
        ):
            problems.append("CRYPTOBOT_NETWORK must be mainnet in production")
        if not self.admin_require_mfa:
            problems.append("ADMIN_REQUIRE_MFA cannot be disabled")
        if problems:
            raise ConfigError("unsafe configuration: " + "; ".join(problems))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.assert_safe_for_environment()
    return settings
