"""the rows are yours: sessions need no task, prompts can be a program's

Until now any project a session ran in put itself on the overlay, so the list held whatever
directory a session had ever started in. `agent_sessions.task_id` turns nullable so that an
unlisted project simply has no row; the rows such directories already left behind go, and
`itopia` joins, inactive until a PC reports for it: red would claim no agent is working there
when nothing is looking.

`prompts.dispatched` marks a prompt a program sent. It starts false everywhere and corrects
itself: a restarted collector resends its whole history, flagged.

`remote_session_id` only ever served the claude.ai link a click used to open.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-04 21:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FK = "agent_sessions_task_id_fkey"
UNWANTED_ROWS = ("ann", "tmpbg7zdsvw", "vs-code")


def upgrade() -> None:
    op.drop_constraint(FK, "agent_sessions", type_="foreignkey")
    op.alter_column("agent_sessions", "task_id", existing_type=sa.Integer(), nullable=True)
    op.create_foreign_key(FK, "agent_sessions", "tasks", ["task_id"], ["id"], ondelete="SET NULL")
    op.drop_column("agent_sessions", "remote_session_id")
    op.add_column(
        "prompts",
        sa.Column("dispatched", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.execute(
        sa.text("DELETE FROM tasks WHERE name = ANY(:names)").bindparams(
            sa.bindparam("names", list(UNWANTED_ROWS), type_=sa.ARRAY(sa.String()))
        )
    )
    op.execute(
        "INSERT INTO tasks (name, active) VALUES ('itopia', false) ON CONFLICT (name) DO NOTHING"
    )


def downgrade() -> None:
    op.drop_column("prompts", "dispatched")
    op.add_column("agent_sessions", sa.Column("remote_session_id", sa.String(100)))
    # A session here has been re-reported within seconds of the server starting again.
    op.execute("DELETE FROM agent_sessions WHERE task_id IS NULL")
    op.drop_constraint(FK, "agent_sessions", type_="foreignkey")
    op.alter_column("agent_sessions", "task_id", existing_type=sa.Integer(), nullable=False)
    op.create_foreign_key(FK, "agent_sessions", "tasks", ["task_id"], ["id"], ondelete="CASCADE")
