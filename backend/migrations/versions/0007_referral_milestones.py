"""Referral ranks: one-time gifts per level reached (by number of invited users who paid).

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-13 02:10:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "referral_milestones",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("level", sa.String(length=16), nullable=False),
        sa.Column("bonus_days", sa.Integer(), server_default="0", nullable=False),
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
            "bonus_days BETWEEN 0 AND 3650", name=op.f("ck_referral_milestones_bonus_days")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_referral_milestones_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_referral_milestones")),
        sa.UniqueConstraint("user_id", "level", name="uq_referral_milestones_user_level"),
    )
    op.create_index(
        op.f("ix_referral_milestones_user_id"), "referral_milestones", ["user_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_referral_milestones_user_id"), table_name="referral_milestones")
    op.drop_table("referral_milestones")
