"""Referral program v2: the invited user gets the discount on their first payment; the referrer
gets free days only (no more referrer discounts that are reserved/used).

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-13 01:55:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        op.f("fk_payments_referral_reward_id_referral_rewards"), "payments", type_="foreignkey"
    )
    op.drop_column("payments", "referral_reward_id")
    op.add_column("payments", sa.Column("referral_percent_off", sa.Integer(), nullable=True))
    op.create_check_constraint(
        op.f("ck_payments_referral_percent_off"),
        "payments",
        "referral_percent_off IS NULL OR referral_percent_off BETWEEN 1 AND 100",
    )
    op.drop_constraint(op.f("ck_referral_rewards_status"), "referral_rewards", type_="check")
    op.drop_constraint(op.f("ck_referral_rewards_percent_off"), "referral_rewards", type_="check")
    op.drop_column("referral_rewards", "status")
    op.drop_column("referral_rewards", "percent_off")
    op.drop_column("referral_rewards", "used_payment_id")


def downgrade() -> None:
    op.add_column("referral_rewards", sa.Column("used_payment_id", sa.UUID(), nullable=True))
    op.add_column(
        "referral_rewards",
        sa.Column("percent_off", sa.Integer(), server_default="30", nullable=False),
    )
    op.add_column(
        "referral_rewards",
        sa.Column("status", sa.String(length=16), server_default="used", nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_referral_rewards_percent_off"), "referral_rewards", "percent_off BETWEEN 1 AND 100"
    )
    op.create_check_constraint(
        op.f("ck_referral_rewards_status"),
        "referral_rewards",
        "status IN ('available', 'reserved', 'used')",
    )
    op.drop_constraint(op.f("ck_payments_referral_percent_off"), "payments", type_="check")
    op.drop_column("payments", "referral_percent_off")
    op.add_column("payments", sa.Column("referral_reward_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("fk_payments_referral_reward_id_referral_rewards"),
        "payments",
        "referral_rewards",
        ["referral_reward_id"],
        ["id"],
        ondelete="SET NULL",
        use_alter=True,
    )
