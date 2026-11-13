"""Traffic accounting (aggregate bytes per device per day) and the referral program.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-13 00:16:48.176129+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "referral_rewards",
        sa.Column("referrer_id", sa.UUID(), nullable=False),
        sa.Column("referred_id", sa.UUID(), nullable=True),
        sa.Column("source_payment_id", sa.UUID(), nullable=True),
        sa.Column("percent_off", sa.Integer(), server_default="30", nullable=False),
        sa.Column("status", sa.String(length=16), server_default="available", nullable=False),
        sa.Column("used_payment_id", sa.UUID(), nullable=True),
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
            "status IN ('available', 'reserved', 'used')", name=op.f("ck_referral_rewards_status")
        ),
        sa.CheckConstraint(
            "percent_off BETWEEN 1 AND 100", name=op.f("ck_referral_rewards_percent_off")
        ),
        sa.ForeignKeyConstraint(
            ["referred_id"],
            ["users.id"],
            name=op.f("fk_referral_rewards_referred_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["referrer_id"],
            ["users.id"],
            name=op.f("fk_referral_rewards_referrer_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_payment_id"],
            ["payments.id"],
            name=op.f("fk_referral_rewards_source_payment_id_payments"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_referral_rewards")),
        sa.UniqueConstraint("referred_id", name=op.f("uq_referral_rewards_referred_id")),
    )
    op.create_index(
        op.f("ix_referral_rewards_referrer_id"), "referral_rewards", ["referrer_id"], unique=False
    )
    op.create_table(
        "device_usage_daily",
        sa.Column("device_id", sa.UUID(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("download_bytes", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("upload_bytes", sa.BigInteger(), server_default="0", nullable=False),
        sa.CheckConstraint(
            "download_bytes >= 0 AND upload_bytes >= 0",
            name=op.f("ck_device_usage_daily_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["device_id"],
            ["devices.id"],
            name=op.f("fk_device_usage_daily_device_id_devices"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("device_id", "day", name=op.f("pk_device_usage_daily")),
    )
    op.create_index(op.f("ix_device_usage_daily_day"), "device_usage_daily", ["day"], unique=False)
    op.add_column("payments", sa.Column("referral_reward_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("fk_payments_referral_reward_id_referral_rewards"),
        "payments",
        "referral_rewards",
        ["referral_reward_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "peer_assignments",
        sa.Column("last_rx_bytes", sa.BigInteger(), server_default="0", nullable=False),
    )
    op.add_column(
        "peer_assignments",
        sa.Column("last_tx_bytes", sa.BigInteger(), server_default="0", nullable=False),
    )
    op.add_column("users", sa.Column("referral_code", sa.String(length=16), nullable=True))
    op.add_column("users", sa.Column("referred_by_id", sa.UUID(), nullable=True))
    op.create_index(op.f("ix_users_referred_by_id"), "users", ["referred_by_id"], unique=False)
    op.create_unique_constraint(op.f("uq_users_referral_code"), "users", ["referral_code"])
    op.create_foreign_key(
        op.f("fk_users_referred_by_id_users"),
        "users",
        "users",
        ["referred_by_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("fk_users_referred_by_id_users"), "users", type_="foreignkey")
    op.drop_constraint(op.f("uq_users_referral_code"), "users", type_="unique")
    op.drop_index(op.f("ix_users_referred_by_id"), table_name="users")
    op.drop_column("users", "referred_by_id")
    op.drop_column("users", "referral_code")
    op.drop_column("peer_assignments", "last_tx_bytes")
    op.drop_column("peer_assignments", "last_rx_bytes")
    op.drop_constraint(
        op.f("fk_payments_referral_reward_id_referral_rewards"), "payments", type_="foreignkey"
    )
    op.drop_column("payments", "referral_reward_id")
    op.drop_index(op.f("ix_device_usage_daily_day"), table_name="device_usage_daily")
    op.drop_table("device_usage_daily")
    op.drop_index(op.f("ix_referral_rewards_referrer_id"), table_name="referral_rewards")
    op.drop_table("referral_rewards")
