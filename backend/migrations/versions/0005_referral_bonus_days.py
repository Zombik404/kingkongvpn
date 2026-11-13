"""Referral bonus: free days credited to the referrer (stored per reward for stats/audit).

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-13 01:40:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "referral_rewards",
        sa.Column("bonus_days", sa.Integer(), server_default="0", nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_referral_rewards_bonus_days"),
        "referral_rewards",
        "bonus_days BETWEEN 0 AND 365",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_referral_rewards_bonus_days"), "referral_rewards", type_="check")
    op.drop_column("referral_rewards", "bonus_days")
