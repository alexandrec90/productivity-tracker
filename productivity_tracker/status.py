"""What colour a task's row is, and which sessions a click on it cycles through.

Shared by the server, which colours each task, and the overlay, which picks the session a
click focuses. Sessions are the JSON-shaped dicts the API returns: only `status` and
`session_id` are read here.
"""

from collections.abc import Iterable, Mapping, Sequence
from enum import StrEnum
from typing import Any

# The values Claude Code writes to `status` in `~/.claude/sessions/<pid>.json`.
BUSY = "busy"
WAITING = "waiting"
IDLE = "idle"
STATUSES = (BUSY, WAITING, IDLE)


class Color(StrEnum):
    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"
    GRAY = "gray"


def normalize_status(raw: object) -> str:
    """A session file's `status`, with anything unrecognised read as idle."""
    return raw if isinstance(raw, str) and raw in STATUSES else IDLE


def task_color(active: bool, statuses: Iterable[str]) -> Color:
    """Yellow beats green: an agent blocked on a question is the row that needs you, even
    while another agent on the same task keeps working."""
    if not active:
        return Color.GRAY
    seen = set(statuses)
    if WAITING in seen:
        return Color.YELLOW
    if BUSY in seen:
        return Color.GREEN
    return Color.RED


_RANK = {WAITING: 0, BUSY: 1, IDLE: 2}


def focus_order(color: Color, sessions: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """The sessions a click cycles through, in order.

    A yellow row cycles through the sessions asking a question and nothing else; any other
    row cycles through every live session, working ones first.
    """
    pool = [s for s in sessions if s["status"] == WAITING] if color is Color.YELLOW else sessions
    return sorted(pool, key=lambda s: (_RANK.get(s["status"], 3), str(s["session_id"])))


def next_session(
    order: Sequence[Mapping[str, Any]], last_session_id: str | None
) -> Mapping[str, Any] | None:
    """The session after the one focused last, wrapping around; the first when the last one
    is gone. Keyed by id rather than index so a session ending mid-cycle skips nothing."""
    if not order:
        return None
    ids = [s["session_id"] for s in order]
    if last_session_id not in ids:
        return order[0]
    return order[(ids.index(last_session_id) + 1) % len(order)]
