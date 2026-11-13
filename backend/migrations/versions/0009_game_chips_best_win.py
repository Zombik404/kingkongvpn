"""Fun chips and the biggest-win leaderboard; the currency of each round.

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-13 19:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "game_profiles", sa.Column("chips", sa.Integer(), server_default="1000", nullable=False)
    )
    op.add_column("game_profiles", sa.Column("chips_day", sa.Date(), nullable=True))
    op.add_column(
        "game_profiles", sa.Column("best_win", sa.Integer(), server_default="0", nullable=False)
    )
    op.add_column(
        "game_profiles",
        sa.Column("best_win_stake", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "game_profiles", sa.Column("best_win_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_check_constraint(
        op.f("ck_game_profiles_chips_non_negative"), "game_profiles", "chips >= 0"
    )
    op.add_column("game_rounds", sa.Column("currency", sa.String(length=8), nullable=True))
    op.execute("UPDATE game_rounds SET currency = 'hours' WHERE stakes")


def downgrade() -> None:
    op.drop_column("game_rounds", "currency")
    op.drop_constraint(op.f("ck_game_profiles_chips_non_negative"), "game_profiles", type_="check")
    for col in ("best_win_at", "best_win_stake", "best_win", "chips_day", "chips"):
        op.drop_column("game_profiles", col)
