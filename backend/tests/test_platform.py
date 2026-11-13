"""Config, email, i18n, audit scrubbing, workers, health, migrations, OpenAPI contract."""

from __future__ import annotations

import datetime as dt
import json
import os
import uuid
from pathlib import Path
from typing import Any
from unittest import mock

import pytest
from alembic import command
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import ConfigError, Settings
from app.core.context import AppContext
from app.core.ids import uuid7
from app.i18n import catalog, negotiate, t
from app.notifications import email as email_mod
from app.notifications.email import EmailJob, render
from app.services.audit import REDACTED, ip_prefix, scrub
from tests.conftest import BACKEND, TEST_DB, alembic_config, make_settings


# --- config -------------------------------------------------------------------------
def test_production_refuses_placeholders(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as exc:
        Settings(
            app_env="production",
            database_url_override=None,
            email_delivery="celery",
            refresh_token_pepper="replace-with-64-random-hex-chars",
            postgres_password="change-me-dev-only",
        ).assert_safe_for_environment()
    msg = str(exc.value)
    for needle in (
        "POSTGRES_PASSWORD",
        "REFRESH_TOKEN_PEPPER",
        "DATA_ENCRYPTION_KEY",
        "JWT_PRIVATE_KEY_FILE",
    ):
        assert needle in msg


def test_production_accepts_real_secrets(tmp_path: Path) -> None:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    key = Ed25519PrivateKey.generate()
    priv, pub = tmp_path / "p.pem", tmp_path / "q.pem"
    priv.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    pub.write_bytes(
        key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    )
    s = Settings(
        app_env="production",
        postgres_password="s3cret-db-pass",
        database_url_override=None,
        refresh_token_pepper=os.urandom(32).hex(),
        data_encryption_key="A" * 43 + "=",
        jwt_private_key_file=priv,
        jwt_public_key_file=pub,
        email_delivery="celery",
        password_hash_profile="default",
    )
    s.assert_safe_for_environment()
    from app.security.tokens import TokenService

    TokenService(s)  # loads real keys


def test_cors_origins_from_env_string() -> None:
    with mock.patch.dict(os.environ, {"CORS_ALLOWED_ORIGINS": "https://a.test, https://b.test"}):
        assert Settings().cors_allowed_origins == ["https://a.test", "https://b.test"]


def test_database_url_assembled() -> None:
    s = Settings(database_url_override=None, postgres_host="db", postgres_password="pw")
    assert s.database_url == "postgresql+asyncpg://globalvpn:pw@db:5432/globalvpn"


# --- ids ---------------------------------------------------------------------------
def test_uuid7_is_time_ordered_v7() -> None:
    ids = [uuid7() for _ in range(2000)]
    assert all(u.version == 7 for u in ids)
    assert ids == sorted(ids)
    assert len(set(ids)) == len(ids)


# --- i18n & email ------------------------------------------------------------------
def test_catalogs_have_identical_keys() -> None:
    def keys(d: dict[str, Any], p: str = "") -> set[str]:
        out: set[str] = set()
        for k, v in d.items():
            out |= keys(v, f"{p}{k}.") if isinstance(v, dict) else {p + k}
        return out

    base = keys(catalog("en"))
    for lang in ("de", "hu", "uk", "ru"):
        assert keys(catalog(lang)) == base, lang


def test_negotiate() -> None:
    assert negotiate("de-AT") == "de"
    assert negotiate(None, "fr-FR,fr;q=0.9,uk;q=0.8,en;q=0.7") == "uk"
    assert negotiate(None, "en;q=0.1, ru;q=0.9") == "ru"
    assert negotiate(None, "xx, yy;q=bad") == "en"
    assert negotiate("zz", None) == "en"
    assert t("ru", "email.missing.key") == "email.missing.key"


@pytest.mark.parametrize("lang", ["en", "de", "hu", "uk", "ru"])
@pytest.mark.parametrize("template", sorted(email_mod.TEMPLATES))
def test_every_email_renders(lang: str, template: str) -> None:
    s = make_settings()
    params = {
        "hours": "24",
        "minutes": "30",
        "plan": "<b>Std</b>",
        "date": "1 Dec 2026",
        "days": "14",
        "rank": "Fox",
        "theme": "Lava",
        "count": "3",
        "code": "AB12CD",
        "result": "win",
        "change": "+2",
        "balance": "5",
    }
    out = render(
        EmailJob(template, "a@example.com", lang, params, "https://w.test/x?token=a&b=1"), s
    )
    assert out.subject and "{" not in out.subject
    assert "{" not in out.text
    assert f'lang="{lang}"' in out.html
    assert "<b>Std</b>" not in out.html  # autoescaped in HTML
    assert "https://w.test/x?token=a&amp;b=1" in out.html


def test_unknown_template_rejected() -> None:
    with pytest.raises(ValueError):
        render(EmailJob("nope", "a@b.c", "en"), make_settings())


def test_email_job_roundtrip_and_smtp() -> None:
    job = EmailJob("verify_email", "a@example.com", "en", {"hours": 24}, "https://x")  # type: ignore[dict-item]
    assert EmailJob.from_dict(json.loads(json.dumps(job.to_dict()))) == EmailJob(
        "verify_email", "a@example.com", "en", {"hours": "24"}, "https://x"
    )
    s = make_settings(
        smtp_host="smtp.test",
        smtp_port=587,
        smtp_starttls=True,
        smtp_username="u",
        smtp_password="p",
        smtp_from="no-reply@vpn.test",
    )
    with mock.patch("smtplib.SMTP") as smtp_cls:
        email_mod.send_smtp(render(job, s), s)
    smtp = smtp_cls.return_value.__enter__.return_value
    smtp_cls.assert_called_once_with("smtp.test", 587, timeout=10.0)
    smtp.starttls.assert_called_once()
    smtp.login.assert_called_once_with("u", "p")
    msg = smtp.send_message.call_args.args[0]
    assert msg["To"] == "a@example.com" and msg["From"] == "no-reply@vpn.test"
    assert msg.is_multipart()


async def test_celery_dispatcher_enqueues_and_never_raises() -> None:
    from app.workers import tasks

    d = email_mod.CeleryDispatcher()
    with mock.patch.object(tasks.send_email, "delay") as delay:
        await d.dispatch(EmailJob("verify_email", "a@b.c", "en"))
    delay.assert_called_once()
    with mock.patch.object(tasks.send_email, "delay", side_effect=ConnectionError("down")):
        await d.dispatch(EmailJob("verify_email", "a@b.c", "en"))  # logged, not raised


async def test_sync_dispatcher_swallows_smtp_errors() -> None:
    d = email_mod.SyncSmtpDispatcher(make_settings(smtp_host="127.0.0.1", smtp_port=1))
    await d.dispatch(EmailJob("verify_email", "a@b.c", "en", {"hours": "1"}, "https://x"))


def test_send_email_task_renders_and_sends() -> None:
    from app.workers import tasks

    with mock.patch.object(tasks, "send_smtp") as send:
        tasks.send_email.run(EmailJob("password_changed", "a@b.c", "de", {}, "https://x").to_dict())
    assert send.call_args.args[0].subject.startswith("Dein")


# --- audit ---------------------------------------------------------------------------
def test_scrub() -> None:
    data = {
        "password": "x",
        "new_password": "y",
        "refresh_token": "t",
        "Authorization": "b",
        "otp_code": "123",
        "nested": {"api_key": "k", "ok": [1, {"secret": 1}]},
        "plan": "standard",
        "long": "z" * 1000,
        "obj": uuid.UUID(int=1),
    }
    out = scrub(data)
    for k in ("password", "new_password", "refresh_token", "Authorization", "otp_code"):
        assert out[k] == REDACTED
    assert out["nested"]["api_key"] == REDACTED
    assert out["nested"]["ok"][1]["secret"] == REDACTED
    assert out["plan"] == "standard"
    assert len(out["long"]) < 300
    assert out["obj"] == str(uuid.UUID(int=1))
    deep: dict[str, Any] = {}
    cur = deep
    for _ in range(10):
        cur["n"] = {}
        cur = cur["n"]
    assert "TRUNCATED" in json.dumps(scrub(deep))


def test_ip_prefix() -> None:
    assert ip_prefix("198.51.100.77") == "198.51.100.0/24"
    assert ip_prefix("2001:db8:1234:5678::1") == "2001:db8:1234::/48"
    assert ip_prefix("not-an-ip") is None
    assert ip_prefix(None) is None


# --- rate limiter fail-open ------------------------------------------------------------
async def test_rate_limiter_fails_open_when_redis_down() -> None:
    from redis.asyncio import Redis

    from app.security.rate_limit import LOGIN_PER_IP, RateLimiter

    dead = Redis.from_url("redis://127.0.0.1:1/0", socket_connect_timeout=0.2)
    limiter = RateLimiter(dead)
    await limiter.hit(LOGIN_PER_IP, "1.2.3.4")
    await limiter.reset(LOGIN_PER_IP, "1.2.3.4")
    await dead.aclose()


# --- workers ------------------------------------------------------------------------
def test_celery_tasks_and_schedule_registered() -> None:
    from app.workers.celery_app import celery_app

    names = set(celery_app.tasks)
    for task in (
        "email.send",
        "subscriptions.process_due",
        "subscriptions.send_reminders",
        "users.purge_deleted",
        "auth.cleanup_tokens",
    ):
        assert task in names
    scheduled = {v["task"] for v in celery_app.conf.beat_schedule.values()}
    assert scheduled <= names
    assert celery_app.conf.task_acks_late is True


async def test_cleanup_tokens(
    ctx: AppContext, client: AsyncClient, outbox: list[Any], db: Any
) -> None:
    from sqlalchemy import func, select, update

    from app.models import AuthSession, UserActionToken
    from app.workers.tasks import cleanup_tokens
    from tests.helpers import new_user

    await new_user(client, outbox, "c1@example.com")
    async with ctx.sessionmaker() as s:
        assert await cleanup_tokens(ctx, s) == 0
    old = dt.datetime.now(dt.UTC) - dt.timedelta(days=8)
    await db.execute(update(AuthSession).values(revoked_at=old))
    await db.execute(update(UserActionToken).values(used_at=old))
    await db.commit()
    async with ctx.sessionmaker() as s:
        assert await cleanup_tokens(ctx, s) == 2
    assert await db.scalar(select(func.count()).select_from(AuthSession)) == 0


def test_periodic_task_wrappers_run(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.workers import tasks

    calls: list[str] = []

    async def fake(ctx: Any, s: Any, **_: Any) -> int:
        calls.append("x")
        return 0

    monkeypatch.setattr(tasks.subs, "process_due", fake)
    monkeypatch.setattr(tasks.subs, "send_reminders", fake)
    monkeypatch.setattr(tasks, "purge_deleted_users", fake)
    monkeypatch.setattr(tasks, "cleanup_tokens", fake)
    for fn in (
        tasks.process_due_task,
        tasks.send_reminders_task,
        tasks.purge_deleted_task,
        tasks.cleanup_tokens_task,
    ):
        assert fn.run() == 0
    assert len(calls) == 4


# --- health & metrics ----------------------------------------------------------------
async def test_health_and_metrics(client: AsyncClient) -> None:
    assert (await client.get("/health/live")).json() == {"status": "ok"}
    ready = await client.get("/health/ready")
    assert ready.status_code == 200
    assert ready.json()["checks"] == {"database": "ok", "redis": "ok"}
    metrics = await client.get("/metrics")
    assert "http_requests_total" in metrics.text


async def test_readiness_reports_degraded(ctx: AppContext, client: AsyncClient) -> None:
    with mock.patch.object(ctx.redis, "ping", side_effect=ConnectionError("down")):
        r = await client.get("/health/ready")
    assert r.status_code == 503
    assert r.json()["checks"]["redis"] == "error"


def test_production_hides_docs() -> None:
    from app.main import create_app

    s = make_settings()
    object.__setattr__(s, "app_env", "production")
    app = create_app(s)
    assert app.openapi_url is None and app.docs_url is None


# --- migrations -------------------------------------------------------------------------
async def test_migrations_up_down_up_on_fresh_database() -> None:
    admin_url = TEST_DB.rsplit("/", 1)[0] + "/postgres"
    name = "globalvpn_migration_check"
    engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    async with engine.connect() as conn:
        await conn.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
        await conn.execute(text(f'CREATE DATABASE "{name}"'))
    url = TEST_DB.rsplit("/", 1)[0] + f"/{name}"
    try:
        cfg = alembic_config(url)
        import asyncio

        await asyncio.to_thread(command.upgrade, cfg, "head")
        await asyncio.to_thread(command.downgrade, cfg, "base")
        await asyncio.to_thread(command.upgrade, cfg, "head")
        check = create_async_engine(url)
        async with check.connect() as conn:
            tables = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'"
                    )
                )
            ).scalar_one()
        await check.dispose()
        assert tables == 34  # 33 app tables + alembic_version
    finally:
        async with engine.connect() as conn:
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        await engine.dispose()


def test_models_match_migrations() -> None:
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from sqlalchemy import create_engine

    from app.models import Base

    sync_url = TEST_DB.replace("+asyncpg", "+psycopg")
    try:
        engine = create_engine(sync_url)
        with engine.connect() as conn:
            diff = compare_metadata(
                MigrationContext.configure(conn, opts={"compare_type": True}), Base.metadata
            )
    except ModuleNotFoundError:
        pytest.skip("psycopg not installed")
    assert diff == []


# --- API contract ------------------------------------------------------------------------
def test_openapi_contract_is_up_to_date() -> None:
    from app.openapi import generate

    committed = BACKEND.parent / "shared" / "api-contracts" / "openapi.json"
    assert committed.is_file(), "run: make openapi"
    assert json.loads(committed.read_text()) == generate(), "contract drift — run: make openapi"


# --- field encryption -------------------------------------------------------------------
def test_field_cipher_key_validation() -> None:
    import base64

    from app.security.crypto import FieldCipher

    good = base64.b64encode(os.urandom(32)).decode()
    c = FieldCipher(make_settings(data_encryption_key=good))
    blob = c.encrypt(b"seed", context=b"ctx")
    assert c.decrypt(blob, context=b"ctx") == b"seed"
    with pytest.raises(ValueError):
        c.decrypt(b"\x02" + blob[1:], context=b"ctx")
    for bad in ("not base64!!", base64.b64encode(b"short").decode()):
        with pytest.raises(ConfigError):
            FieldCipher(make_settings(data_encryption_key=bad))
    prod = make_settings()
    object.__setattr__(prod, "app_env", "production")
    with pytest.raises(ConfigError):
        FieldCipher(prod)


def test_jwt_key_loading_edge_cases(tmp_path: Path) -> None:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    from app.security.tokens import TokenService

    priv, pub = tmp_path / "k.pem", tmp_path / "p.pem"
    ec_key = ec.generate_private_key(ec.SECP256R1())
    priv.write_bytes(
        ec_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    pub.write_bytes(
        ec_key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    )
    with pytest.raises(ConfigError, match="Ed25519"):
        TokenService(make_settings(jwt_private_key_file=priv, jwt_public_key_file=pub))
    # unreadable files: dev falls back to an ephemeral key, production refuses to start
    s = make_settings(jwt_private_key_file=priv, jwt_public_key_file=pub)
    with mock.patch.object(Path, "read_bytes", side_effect=PermissionError("denied")):
        TokenService(s)
        object.__setattr__(s, "app_env", "production")
        with pytest.raises(ConfigError, match="cannot read"):
            TokenService(s)
    object.__setattr__(s, "jwt_private_key_file", None)
    with pytest.raises(ConfigError, match="required"):
        TokenService(s)
