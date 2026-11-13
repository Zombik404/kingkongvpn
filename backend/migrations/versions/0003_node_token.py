"""Node API token (test-phase node auth, ADR-017).

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "servers", sa.Column("agent_token_hash", sa.LargeBinary(length=32), nullable=True)
    )
    op.create_unique_constraint(
        op.f("uq_servers_agent_token_hash"), "servers", ["agent_token_hash"]
    )


def downgrade() -> None:
    op.drop_constraint(op.f("uq_servers_agent_token_hash"), "servers", type_="unique")
    op.drop_column("servers", "agent_token_hash")
