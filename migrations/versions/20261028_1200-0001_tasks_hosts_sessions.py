"""tasks, hosts and agent_sessions

Revision ID: 0001
Revises:
Create Date: 2026-10-28 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tasks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False, unique=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_table(
        "hosts",
        sa.Column("name", sa.String(200), primary_key=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "agent_sessions",
        sa.Column(
            "host",
            sa.String(200),
            sa.ForeignKey("hosts.name", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("session_id", sa.String(100), primary_key=True),
        sa.Column(
            "task_id",
            sa.Integer(),
            sa.ForeignKey("tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("pid", sa.Integer(), nullable=False),
        sa.Column("cwd", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("waiting_for", sa.Text(), nullable=True),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("kind", sa.String(40), nullable=True),
        sa.Column("remote_session_id", sa.String(100), nullable=True),
        sa.Column("status_updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_agent_sessions_task_id", "agent_sessions", ["task_id"])


def downgrade() -> None:
    op.drop_table("agent_sessions")
    op.drop_table("hosts")
    op.drop_table("tasks")
