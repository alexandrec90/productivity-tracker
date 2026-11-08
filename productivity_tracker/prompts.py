"""The prompts sent to agents, read from Claude Code's prompt history (`history.jsonl`).

Claude Code appends one line per prompt, with its time, its session and the directory it was
typed in, whether it was typed in the terminal or sent through Remote Control. Only those three
leave this PC: the prompt's text never does. Slash commands (`/clear`) and shell escapes
(`!ls`) are not prompts to an agent, so they are left out.

History records no author, and neither does the transcript, which says a scheduled fixer's
brief was `typed` by a `human`: to Claude Code it was. All that gives one away is its text, so
that opening sentence is read here, and only the verdict leaves this PC. A session opened
with such a brief is a dispatched session, and is no agent of yours either.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import cache
from pathlib import Path

from productivity_tracker.sessions import project_name

_NOT_PROMPTS = ("/", "!")
# How a program's brief opens: devkit's fix pass, `ROLE` in its `fix_prompts.py`.
_DISPATCHED = ("You are a fixer session",)


@dataclass(frozen=True)
class Prompt:
    session_id: str
    at: str  # ISO 8601, UTC
    project: str
    dispatched: bool = False


def parse_prompt(raw: object, project_of: Callable[[str], str] = project_name) -> Prompt | None:
    """One history line's JSON, or None for a line that is not a prompt to an agent."""
    if not isinstance(raw, dict):
        return None
    display, timestamp, project = raw.get("display"), raw.get("timestamp"), raw.get("project")
    if not isinstance(display, str) or not isinstance(project, str) or not project:
        return None
    if not isinstance(timestamp, int | float) or isinstance(timestamp, bool):
        return None
    text = display.strip()
    if not text or text.startswith(_NOT_PROMPTS):
        return None
    session_id = raw.get("sessionId")
    return Prompt(
        # Old Claude Code versions wrote no session id; such prompts still count.
        session_id=session_id if isinstance(session_id, str) else "",
        at=datetime.fromtimestamp(timestamp / 1000, tz=UTC).isoformat(),
        project=project_of(project),
        dispatched=text.startswith(_DISPATCHED),
    )


def read_prompts(path: Path, project_of: Callable[[str], str] = project_name) -> list[Prompt]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    found: list[Prompt] = []
    for line in lines:
        try:
            raw = json.loads(line)
        except ValueError:
            # The last line can be half-written; the next read picks it up whole.
            continue
        prompt = parse_prompt(raw, project_of)
        if prompt is not None:
            found.append(prompt)
    return found


def _signature(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return stat.st_mtime_ns, stat.st_size


class PromptFeed:
    """The prompts of `path` the server has not acknowledged yet, at most `batch` at a time.

    The whole history goes up once, so records and streaks reach back before the collector
    was installed; the server ignores a prompt it already has, so a restarted collector simply
    sends it again. The file is re-read only when it changes.
    """

    def __init__(self, path: Path, batch: int = 500) -> None:
        self.path = path
        self.batch = batch
        self._signature: tuple[int, int] | None = None
        self._unsent: list[Prompt] = []
        self._sent: set[tuple[str, str]] = set()
        # The same few directories recur thousands of times, and each lookup walks the disk.
        self._project_of = cache(project_name)
        self.dispatched_sessions: set[str] = set()

    def pending(self) -> list[Prompt]:
        signature = _signature(self.path)
        if signature != self._signature:
            self._signature = signature
            prompts = read_prompts(self.path, self._project_of)
            self.dispatched_sessions = {p.session_id for p in prompts if p.dispatched}
            self._unsent = [p for p in prompts if (p.session_id, p.at) not in self._sent]
        return self._unsent[: self.batch]

    def delivered(self, prompts: list[Prompt]) -> None:
        keys = {(p.session_id, p.at) for p in prompts}
        self._sent |= keys
        self._unsent = [p for p in self._unsent if (p.session_id, p.at) not in keys]
