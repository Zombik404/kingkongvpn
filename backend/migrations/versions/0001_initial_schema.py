"""Initial schema: all tables from Architecture §4.

Reviewed by hand after autogenerate. Requires the `citext` extension (created here if the
role may; in managed Postgres create it once as an admin).

Revision ID: 0001
Revises:
Create Date: 2026-11-12 21:55:58.998492+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")
    # Monotonic source of tunnel address offsets (app.vpn.allocator).
    op.execute("CREATE SEQUENCE IF NOT EXISTS tunnel_address_seq AS bigint START 1 NO CYCLE")
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("actor_id", sa.UUID(), nullable=True),
        sa.Column("actor_type", sa.String(length=16), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=True),
        sa.Column("target_id", sa.String(length=64), nullable=True),
        sa.Column("result", sa.String(length=16), nullable=False),
        sa.Column("ip_prefix", sa.String(length=64), nullable=True),
        sa.Column(
            "details", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
        sa.CheckConstraint(
            "actor_type IN ('user', 'admin', 'system', 'service', 'anonymous')",
            name=op.f("ck_audit_logs_actor_type"),
        ),
        sa.CheckConstraint(
            "result IN ('success', 'denied', 'failure')", name=op.f("ck_audit_logs_result")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_logs")),
    )
    op.create_index(op.f("ix_audit_logs_action"), "audit_logs", ["action"], unique=False)
    op.create_index(op.f("ix_audit_logs_actor_id"), "audit_logs", ["actor_id"], unique=False)
    op.create_index(op.f("ix_audit_logs_created_at"), "audit_logs", ["created_at"], unique=False)
    op.create_index(
        "ix_audit_logs_target", "audit_logs", ["target_type", "target_id"], unique=False
    )
    op.create_table(
        "campaigns",
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_campaigns")),
    )
    op.create_table(
        "locations",
        sa.Column("country_code", sa.String(length=2), nullable=False),
        sa.Column("city", sa.String(length=64), nullable=True),
        sa.Column(
            "names", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("country_code ~ '^[A-Z]{2}$'", name=op.f("ck_locations_country_code")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_locations")),
        sa.UniqueConstraint("country_code", "city", name="uq_locations_country_city"),
    )
    op.create_table(
        "payment_events",
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("event_id", sa.String(length=255), nullable=False),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result", sa.String(length=64), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.CheckConstraint(
            "provider IN ('trial', 'promo', 'admin', 'stripe', 'apple', 'google', 'telegram', 'paypal')",
            name=op.f("ck_payment_events_provider"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payment_events")),
        sa.UniqueConstraint("provider", "event_id", name="uq_payment_events_provider_event"),
    )
    op.create_table(
        "plans",
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column(
            "names", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
        sa.Column(
            "features", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
        sa.Column(
            "server_tiers",
            postgresql.ARRAY(sa.String(length=16)),
            server_default=sa.text("'{standard}'"),
            nullable=False,
        ),
        sa.Column("device_limit", sa.Integer(), server_default="5", nullable=False),
        sa.Column("is_trial", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("code ~ '^[a-z0-9][a-z0-9_-]{1,31}$'", name=op.f("ck_plans_code")),
        sa.CheckConstraint("device_limit BETWEEN 1 AND 100", name=op.f("ck_plans_device_limit")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_plans")),
        sa.UniqueConstraint("code", name=op.f("uq_plans_code")),
    )
    op.create_table(
        "users",
        sa.Column("email", postgresql.CITEXT(), nullable=True),
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("password_hash", sa.String(length=255), nullable=True),
        sa.Column("telegram_id", sa.BigInteger(), nullable=True),
        sa.Column("locale", sa.String(length=8), server_default="en", nullable=False),
        sa.Column("status", sa.String(length=16), server_default="active", nullable=False),
        sa.Column(
            "roles",
            postgresql.ARRAY(sa.String(length=32)),
            server_default=sa.text("'{}'::varchar[]"),
            nullable=False,
        ),
        sa.Column("token_version", sa.Integer(), server_default="0", nullable=False),
        sa.Column("totp_secret_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("totp_enabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("totp_last_counter", sa.BigInteger(), nullable=True),
        sa.Column("trial_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('active', 'suspended', 'deleted')", name=op.f("ck_users_status")
        ),
        sa.CheckConstraint("char_length(locale) BETWEEN 2 AND 8", name=op.f("ck_users_locale")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
        sa.UniqueConstraint("telegram_id", name=op.f("uq_users_telegram_id")),
    )
    op.create_index(op.f("ix_users_deleted_at"), "users", ["deleted_at"], unique=False)
    op.create_table(
        "auth_sessions",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoke_reason", sa.String(length=32), nullable=True),
        sa.Column("mfa_verified", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("user_agent", sa.String(length=256), nullable=True),
        sa.Column("ip_prefix", sa.String(length=64), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_auth_sessions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_auth_sessions")),
    )
    op.create_index(op.f("ix_auth_sessions_user_id"), "auth_sessions", ["user_id"], unique=False)
    op.create_table(
        "devices",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("platform", sa.String(length=16), nullable=False),
        sa.Column("public_key", sa.String(length=44), nullable=False),
        sa.Column("address_index", sa.BigInteger(), nullable=True),
        sa.Column("ipv4", postgresql.INET(), nullable=True),
        sa.Column("ipv6", postgresql.INET(), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="active", nullable=False),
        sa.Column("last_handshake_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "platform IN ('android', 'ios', 'windows', 'macos', 'linux', 'router', 'other')",
            name=op.f("ck_devices_platform"),
        ),
        sa.CheckConstraint("status IN ('active', 'revoked')", name=op.f("ck_devices_status")),
        sa.CheckConstraint(
            "address_index IS NULL OR address_index >= 0", name=op.f("ck_devices_address_index")
        ),
        sa.CheckConstraint("char_length(public_key) = 44", name=op.f("ck_devices_public_key_len")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_devices_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_devices")),
        sa.UniqueConstraint("address_index", name=op.f("uq_devices_address_index")),
        sa.UniqueConstraint("ipv4", name=op.f("uq_devices_ipv4")),
        sa.UniqueConstraint("ipv6", name=op.f("uq_devices_ipv6")),
        sa.UniqueConstraint("public_key", name=op.f("uq_devices_public_key")),
    )
    op.create_index(op.f("ix_devices_user_id"), "devices", ["user_id"], unique=False)
    op.create_table(
        "notification_preferences",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("email_marketing", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("email_service", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("telegram", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("push", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_notification_preferences_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_notification_preferences")),
    )
    op.create_table(
        "notifications",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column(
            "payload", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
        sa.Column("status", sa.String(length=16), server_default="queued", nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.String(length=255), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "channel IN ('email', 'telegram', 'push')", name=op.f("ck_notifications_channel")
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'sent', 'failed')", name=op.f("ck_notifications_status")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_notifications_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notifications")),
    )
    op.create_index(op.f("ix_notifications_user_id"), "notifications", ["user_id"], unique=False)
    op.create_table(
        "plan_prices",
        sa.Column("plan_id", sa.UUID(), nullable=False),
        sa.Column("period_unit", sa.String(length=8), nullable=False),
        sa.Column("period_count", sa.Integer(), server_default="1", nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("amount_minor", sa.Integer(), nullable=False),
        sa.Column(
            "provider_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name=op.f("ck_plan_prices_currency")),
        sa.CheckConstraint(
            "period_unit IN ('day', 'month', 'year')", name=op.f("ck_plan_prices_period_unit")
        ),
        sa.CheckConstraint("amount_minor >= 0", name=op.f("ck_plan_prices_amount_minor")),
        sa.CheckConstraint(
            "period_count BETWEEN 1 AND 36", name=op.f("ck_plan_prices_period_count")
        ),
        sa.ForeignKeyConstraint(
            ["plan_id"], ["plans.id"], name=op.f("fk_plan_prices_plan_id_plans"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_plan_prices")),
    )
    op.create_index(op.f("ix_plan_prices_plan_id"), "plan_prices", ["plan_id"], unique=False)
    op.create_table(
        "promo_codes",
        sa.Column("code", postgresql.CITEXT(), nullable=False),
        sa.Column("campaign_id", sa.UUID(), nullable=True),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("percent_off", sa.Integer(), nullable=True),
        sa.Column("amount_off_minor", sa.Integer(), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("free_days", sa.Integer(), nullable=True),
        sa.Column("plan_id", sa.UUID(), nullable=True),
        sa.Column("max_redemptions", sa.Integer(), nullable=True),
        sa.Column("redemption_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(kind = 'percent_off' AND percent_off BETWEEN 1 AND 100) OR (kind = 'amount_off' AND amount_off_minor > 0 AND currency IS NOT NULL) OR (kind = 'free_days' AND free_days BETWEEN 1 AND 366 AND plan_id IS NOT NULL)",
            name=op.f("ck_promo_codes_kind_fields"),
        ),
        sa.CheckConstraint(
            "kind IN ('percent_off', 'amount_off', 'free_days')", name=op.f("ck_promo_codes_kind")
        ),
        sa.CheckConstraint(
            "max_redemptions IS NULL OR max_redemptions > 0",
            name=op.f("ck_promo_codes_max_redemptions"),
        ),
        sa.CheckConstraint("redemption_count >= 0", name=op.f("ck_promo_codes_redemption_count")),
        sa.ForeignKeyConstraint(
            ["campaign_id"],
            ["campaigns.id"],
            name=op.f("fk_promo_codes_campaign_id_campaigns"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["plan_id"],
            ["plans.id"],
            name=op.f("fk_promo_codes_plan_id_plans"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_promo_codes")),
        sa.UniqueConstraint("code", name=op.f("uq_promo_codes_code")),
    )
    op.create_table(
        "servers",
        sa.Column("location_id", sa.UUID(), nullable=False),
        sa.Column("hostname", sa.String(length=253), nullable=False),
        sa.Column("public_ipv4", postgresql.INET(), nullable=True),
        sa.Column("public_ipv6", postgresql.INET(), nullable=True),
        sa.Column("endpoint_port", sa.Integer(), server_default="51820", nullable=False),
        sa.Column("wg_public_key", sa.String(length=44), nullable=True),
        sa.Column("tier", sa.String(length=16), server_default="standard", nullable=False),
        sa.Column("status", sa.String(length=16), server_default="provisioning", nullable=False),
        sa.Column("max_peers", sa.Integer(), server_default="1500", nullable=False),
        sa.Column("bandwidth_capacity_mbps", sa.Integer(), nullable=True),
        sa.Column("agent_cert_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("revision", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('provisioning', 'active', 'draining', 'maintenance', 'disabled')",
            name=op.f("ck_servers_status"),
        ),
        sa.CheckConstraint(
            "endpoint_port BETWEEN 1 AND 65535", name=op.f("ck_servers_endpoint_port")
        ),
        sa.CheckConstraint("max_peers > 0", name=op.f("ck_servers_max_peers")),
        sa.ForeignKeyConstraint(
            ["location_id"],
            ["locations.id"],
            name=op.f("fk_servers_location_id_locations"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_servers")),
        sa.UniqueConstraint(
            "agent_cert_fingerprint", name=op.f("uq_servers_agent_cert_fingerprint")
        ),
        sa.UniqueConstraint("hostname", name=op.f("uq_servers_hostname")),
        sa.UniqueConstraint("wg_public_key", name=op.f("uq_servers_wg_public_key")),
    )
    op.create_index(op.f("ix_servers_location_id"), "servers", ["location_id"], unique=False)
    op.create_table(
        "settings",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_by", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["users.id"],
            name=op.f("fk_settings_updated_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_settings")),
    )
    op.create_table(
        "support_tickets",
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("subject", sa.String(length=200), nullable=False),
        sa.Column("priority", sa.String(length=16), server_default="normal", nullable=False),
        sa.Column("status", sa.String(length=16), server_default="open", nullable=False),
        sa.Column("assignee_id", sa.UUID(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "priority IN ('low', 'normal', 'high', 'urgent')",
            name=op.f("ck_support_tickets_priority"),
        ),
        sa.CheckConstraint(
            "status IN ('open', 'pending', 'resolved', 'closed')",
            name=op.f("ck_support_tickets_status"),
        ),
        sa.ForeignKeyConstraint(
            ["assignee_id"],
            ["users.id"],
            name=op.f("fk_support_tickets_assignee_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_support_tickets_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_support_tickets")),
    )
    op.create_index(
        op.f("ix_support_tickets_user_id"), "support_tickets", ["user_id"], unique=False
    )
    op.create_table(
        "user_action_tokens",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.CheckConstraint(
            "purpose IN ('verify_email', 'reset_password')",
            name=op.f("ck_user_action_tokens_purpose"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_user_action_tokens_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_action_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_user_action_tokens_token_hash")),
    )
    op.create_index(
        op.f("ix_user_action_tokens_user_id"), "user_action_tokens", ["user_id"], unique=False
    )
    op.create_table(
        "peer_assignments",
        sa.Column("device_id", sa.UUID(), nullable=False),
        sa.Column("server_id", sa.UUID(), nullable=False),
        sa.Column("state", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column(
            "assigned_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revision", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "state IN ('pending', 'active', 'removing')", name=op.f("ck_peer_assignments_state")
        ),
        sa.ForeignKeyConstraint(
            ["device_id"],
            ["devices.id"],
            name=op.f("fk_peer_assignments_device_id_devices"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["server_id"],
            ["servers.id"],
            name=op.f("fk_peer_assignments_server_id_servers"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_peer_assignments")),
        sa.UniqueConstraint("device_id", "server_id", name="uq_peer_assignments_device_server"),
    )
    op.create_index(
        op.f("ix_peer_assignments_device_id"), "peer_assignments", ["device_id"], unique=False
    )
    op.create_index(
        op.f("ix_peer_assignments_server_id"), "peer_assignments", ["server_id"], unique=False
    )
    op.create_table(
        "refresh_tokens",
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replaced_by_id", sa.UUID(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["replaced_by_id"],
            ["refresh_tokens.id"],
            name=op.f("fk_refresh_tokens_replaced_by_id_refresh_tokens"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["auth_sessions.id"],
            name=op.f("fk_refresh_tokens_session_id_auth_sessions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_refresh_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_refresh_tokens_token_hash")),
    )
    op.create_index(
        op.f("ix_refresh_tokens_session_id"), "refresh_tokens", ["session_id"], unique=False
    )
    op.create_table(
        "subscriptions",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("plan_id", sa.UUID(), nullable=False),
        sa.Column("plan_price_id", sa.UUID(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("provider_subscription_id", sa.String(length=255), nullable=True),
        sa.Column("auto_renew", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("current_period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cancel_at_period_end", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("canceled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("grace_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reminder_sent_for", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reminder_threshold_days", sa.Integer(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "provider IN ('trial', 'promo', 'admin', 'stripe', 'apple', 'google', 'telegram', 'paypal')",
            name=op.f("ck_subscriptions_provider"),
        ),
        sa.CheckConstraint(
            "status IN ('trialing', 'active', 'past_due', 'grace', 'canceled', 'expired', 'refunded')",
            name=op.f("ck_subscriptions_status"),
        ),
        sa.CheckConstraint(
            "current_period_end > current_period_start", name=op.f("ck_subscriptions_period")
        ),
        sa.ForeignKeyConstraint(
            ["plan_id"],
            ["plans.id"],
            name=op.f("fk_subscriptions_plan_id_plans"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["plan_price_id"],
            ["plan_prices.id"],
            name=op.f("fk_subscriptions_plan_price_id_plan_prices"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_subscriptions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_subscriptions")),
        sa.UniqueConstraint(
            "provider", "provider_subscription_id", name="uq_subscriptions_provider_sub_id"
        ),
    )
    op.create_index(
        "ix_subscriptions_status_period_end",
        "subscriptions",
        ["status", "current_period_end"],
        unique=False,
    )
    op.create_index(op.f("ix_subscriptions_user_id"), "subscriptions", ["user_id"], unique=False)
    op.create_index(
        "uq_subscriptions_one_live_per_user",
        "subscriptions",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('trialing', 'active', 'past_due', 'grace')"),
    )
    op.create_table(
        "ticket_messages",
        sa.Column("ticket_id", sa.UUID(), nullable=False),
        sa.Column("author_id", sa.UUID(), nullable=True),
        sa.Column("author_type", sa.String(length=8), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("internal", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "author_type IN ('user', 'staff')", name=op.f("ck_ticket_messages_author_type")
        ),
        sa.ForeignKeyConstraint(
            ["author_id"],
            ["users.id"],
            name=op.f("fk_ticket_messages_author_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["ticket_id"],
            ["support_tickets.id"],
            name=op.f("fk_ticket_messages_ticket_id_support_tickets"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ticket_messages")),
    )
    op.create_index(
        op.f("ix_ticket_messages_ticket_id"), "ticket_messages", ["ticket_id"], unique=False
    )
    op.create_table(
        "family_members",
        sa.Column("subscription_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("role", sa.String(length=16), server_default="member", nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("role IN ('owner', 'member')", name=op.f("ck_family_members_role")),
        sa.ForeignKeyConstraint(
            ["subscription_id"],
            ["subscriptions.id"],
            name=op.f("fk_family_members_subscription_id_subscriptions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_family_members_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_family_members")),
        sa.UniqueConstraint("subscription_id", "user_id", name="uq_family_members_sub_user"),
    )
    op.create_index(
        op.f("ix_family_members_subscription_id"),
        "family_members",
        ["subscription_id"],
        unique=False,
    )
    op.create_index(op.f("ix_family_members_user_id"), "family_members", ["user_id"], unique=False)
    op.create_table(
        "payments",
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("subscription_id", sa.UUID(), nullable=True),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("provider_payment_id", sa.String(length=255), nullable=False),
        sa.Column("amount_minor", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name=op.f("ck_payments_currency")),
        sa.CheckConstraint(
            "kind IN ('initial', 'renewal', 'refund')", name=op.f("ck_payments_kind")
        ),
        sa.CheckConstraint(
            "provider IN ('trial', 'promo', 'admin', 'stripe', 'apple', 'google', 'telegram', 'paypal')",
            name=op.f("ck_payments_provider"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'succeeded', 'failed', 'refunded')",
            name=op.f("ck_payments_status"),
        ),
        sa.ForeignKeyConstraint(
            ["subscription_id"],
            ["subscriptions.id"],
            name=op.f("fk_payments_subscription_id_subscriptions"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_payments_user_id_users"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payments")),
        sa.UniqueConstraint(
            "provider", "provider_payment_id", name="uq_payments_provider_payment_id"
        ),
    )
    op.create_index(op.f("ix_payments_user_id"), "payments", ["user_id"], unique=False)
    op.create_table(
        "promo_redemptions",
        sa.Column("promo_code_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("subscription_id", sa.UUID(), nullable=True),
        sa.Column(
            "redeemed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["promo_code_id"],
            ["promo_codes.id"],
            name=op.f("fk_promo_redemptions_promo_code_id_promo_codes"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["subscription_id"],
            ["subscriptions.id"],
            name=op.f("fk_promo_redemptions_subscription_id_subscriptions"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_promo_redemptions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_promo_redemptions")),
        sa.UniqueConstraint("promo_code_id", "user_id", name="uq_promo_redemptions_code_user"),
    )
    op.create_index(
        op.f("ix_promo_redemptions_promo_code_id"),
        "promo_redemptions",
        ["promo_code_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_promo_redemptions_user_id"), "promo_redemptions", ["user_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_promo_redemptions_user_id"), table_name="promo_redemptions")
    op.drop_index(op.f("ix_promo_redemptions_promo_code_id"), table_name="promo_redemptions")
    op.drop_table("promo_redemptions")
    op.drop_index(op.f("ix_payments_user_id"), table_name="payments")
    op.drop_table("payments")
    op.drop_index(op.f("ix_family_members_user_id"), table_name="family_members")
    op.drop_index(op.f("ix_family_members_subscription_id"), table_name="family_members")
    op.drop_table("family_members")
    op.drop_index(op.f("ix_ticket_messages_ticket_id"), table_name="ticket_messages")
    op.drop_table("ticket_messages")
    op.drop_index(
        "uq_subscriptions_one_live_per_user",
        table_name="subscriptions",
        postgresql_where=sa.text("status IN ('trialing', 'active', 'past_due', 'grace')"),
    )
    op.drop_index(op.f("ix_subscriptions_user_id"), table_name="subscriptions")
    op.drop_index("ix_subscriptions_status_period_end", table_name="subscriptions")
    op.drop_table("subscriptions")
    op.drop_index(op.f("ix_refresh_tokens_session_id"), table_name="refresh_tokens")
    op.drop_table("refresh_tokens")
    op.drop_index(op.f("ix_peer_assignments_server_id"), table_name="peer_assignments")
    op.drop_index(op.f("ix_peer_assignments_device_id"), table_name="peer_assignments")
    op.drop_table("peer_assignments")
    op.drop_index(op.f("ix_user_action_tokens_user_id"), table_name="user_action_tokens")
    op.drop_table("user_action_tokens")
    op.drop_index(op.f("ix_support_tickets_user_id"), table_name="support_tickets")
    op.drop_table("support_tickets")
    op.drop_table("settings")
    op.drop_index(op.f("ix_servers_location_id"), table_name="servers")
    op.drop_table("servers")
    op.drop_table("promo_codes")
    op.drop_index(op.f("ix_plan_prices_plan_id"), table_name="plan_prices")
    op.drop_table("plan_prices")
    op.drop_index(op.f("ix_notifications_user_id"), table_name="notifications")
    op.drop_table("notifications")
    op.drop_table("notification_preferences")
    op.drop_index(op.f("ix_devices_user_id"), table_name="devices")
    op.drop_table("devices")
    op.drop_index(op.f("ix_auth_sessions_user_id"), table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_index(op.f("ix_users_deleted_at"), table_name="users")
    op.drop_table("users")
    op.drop_table("plans")
    op.drop_table("payment_events")
    op.drop_table("locations")
    op.drop_table("campaigns")
    op.drop_index("ix_audit_logs_target", table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_created_at"), table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_actor_id"), table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_action"), table_name="audit_logs")
    op.drop_table("audit_logs")
    op.execute("DROP SEQUENCE IF EXISTS tunnel_address_seq")
