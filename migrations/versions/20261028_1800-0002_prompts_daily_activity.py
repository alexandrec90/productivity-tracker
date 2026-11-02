"""prompts and daily_activity, behind the scoreboard

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-28 18:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "prompts",
        sa.Column("host", sa.String(200), primary_key=True),
        sa.Column("session_id", sa.String(100), primary_key=True),
        sa.Column("at", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("project", sa.String(200), nullable=False),
    )
    op.create_index("ix_prompts_at", "prompts", ["at"])
    op.create_table(
        "daily_activity",
        sa.Column("day", sa.Date(), primary_key=True),
        sa.Column("busy_seconds", sa.Float(), nullable=False, server_default=sa.text("0")),
        sa.Column("waiting_seconds", sa.Float(), nullable=False, server_default=sa.text("0")),
        sa.Column("peak_busy", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )


def downgrade() -> None:
    op.drop_table("daily_activity")
    op.drop_table("prompts")
