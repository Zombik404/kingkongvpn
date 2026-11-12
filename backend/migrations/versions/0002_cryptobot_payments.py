"""Crypto Pay (@CryptoBot) payments: provider value + checkout columns on payments.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = "('trial', 'promo', 'admin', 'stripe', 'apple', 'google', 'telegram', 'paypal')"
NEW = "('trial', 'promo', 'admin', 'stripe', 'apple', 'google', 'telegram', 'paypal', 'cryptobot')"
TABLES = ("subscriptions", "payments", "payment_events")


def _provider_check(values: str) -> None:
    for table in TABLES:
        op.drop_constraint(op.f(f"ck_{table}_provider"), table, type_="check")
        op.create_check_constraint(op.f(f"ck_{table}_provider"), table, f"provider IN {values}")


def upgrade() -> None:
    _provider_check(NEW)
    op.add_column("payments", sa.Column("plan_price_id", sa.UUID(), nullable=True))
    op.add_column("payments", sa.Column("promo_code_id", sa.UUID(), nullable=True))
    op.add_column("payments", sa.Column("checkout_url", sa.String(length=512), nullable=True))
    op.add_column("payments", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("payments", sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("payments", sa.Column("paid_asset", sa.String(length=16), nullable=True))
    op.add_column("payments", sa.Column("paid_amount", sa.String(length=64), nullable=True))
    op.add_column("payments", sa.Column("failure_reason", sa.String(length=64), nullable=True))
    op.create_foreign_key(
        op.f("fk_payments_plan_price_id_plan_prices"),
        "payments",
        "plan_prices",
        ["plan_price_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("fk_payments_promo_code_id_promo_codes"),
        "payments",
        "promo_codes",
        ["promo_code_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_payments_status_provider", "payments", ["status", "provider"])


def downgrade() -> None:
    op.drop_index("ix_payments_status_provider", table_name="payments")
    op.drop_constraint(
        op.f("fk_payments_promo_code_id_promo_codes"), "payments", type_="foreignkey"
    )
    op.drop_constraint(
        op.f("fk_payments_plan_price_id_plan_prices"), "payments", type_="foreignkey"
    )
    for col in (
        "failure_reason",
        "paid_amount",
        "paid_asset",
        "paid_at",
        "expires_at",
        "checkout_url",
        "promo_code_id",
        "plan_price_id",
    ):
        op.drop_column("payments", col)
    op.execute("DELETE FROM payment_events WHERE provider = 'cryptobot'")
    op.execute("DELETE FROM payments WHERE provider = 'cryptobot'")
    op.execute("UPDATE subscriptions SET provider = 'admin' WHERE provider = 'cryptobot'")
    _provider_check(OLD)
