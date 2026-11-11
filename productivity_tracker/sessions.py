"""Read the Claude Code sessions live on this PC.

Claude Code keeps one `sessions/<pid>.json` per running process in its config directory and
rewrites its `status` as the agent works: `busy` mid-turn, `waiting` when it is blocked on
you (a question, a permission prompt, a dialog), `idle` once the turn ends. Reading those
files is the whole collector: no hook, no wrapper around `claude`.

A file outlives a process that crashed, so each one is checked against the process table:
the pid must be alive, and on Windows its creation time must match the file's `procStart`,
or a recycled pid would resurrect a dead session.

Only sessions you opened count. A `claude remote-control` server spawns its sessions headless
through the SDK, and so does `claude -p`: such a file says `"entrypoint": "sdk-cli"`, and has
no terminal to focus.
"""

import json
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import psutil

from productivity_tracker.status import normalize_status

# Seconds between 1601-01-01 (a Windows FILETIME's epoch) and 1970-01-01.
_FILETIME_EPOCH_OFFSET = 11_644_473_600


@dataclass(frozen=True)
class LiveSession:
    session_id: str
    pid: int
    project: str
    cwd: str
    status: str
    waiting_for: str | None
    name: str | None
    kind: str | None
    status_updated_at: str | None


def claude_config_dir(override: Path | None = None) -> Path:
    if override is not None:
        return override
    env = os.environ.get("CLAUDE_CONFIG_DIR")
    return Path(env) if env else Path.home() / ".claude"


def project_root(cwd: Path) -> Path:
    """The checkout a session belongs to, with worktrees folded into their main repository,
    so every agent on one project lands on one row whichever worktree it runs in."""
    parts = cwd.parts
    for i in range(len(parts) - 1):
        if parts[i] == ".claude" and parts[i + 1] == "worktrees" and i > 0:
            return Path(*parts[:i])
    for directory in (cwd, *cwd.parents):
        marker = directory / ".git"
        if marker.is_dir():
            return directory
        if marker.is_file():
            return _main_checkout(directory, marker)
    return cwd


def _main_checkout(directory: Path, marker: Path) -> Path:
    # A linked worktree's `.git` is a file: `gitdir: <main>/.git/worktrees/<name>`.
    try:
        text = marker.read_text(encoding="utf-8").strip()
    except OSError:
        return directory
    gitdir = text.removeprefix("gitdir:").strip().replace("\\", "/")
    main, sep, _ = gitdir.partition("/.git/worktrees/")
    return Path(main) if sep else directory


def project_name(cwd: str) -> str:
    root = project_root(Path(cwd))
    return root.name or str(root)


def filetime_to_epoch(filetime: int) -> float:
    return filetime / 10_000_000 - _FILETIME_EPOCH_OFFSET


def is_alive(pid: int, proc_start: str | None) -> bool:
    try:
        process = psutil.Process(pid)
        created = process.create_time()
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return False
    if sys.platform != "win32" or not proc_start or not proc_start.isdigit():
        return True
    return abs(created - filetime_to_epoch(int(proc_start))) < 2.0


def _iso_from_ms(value: object) -> str | None:
    if not isinstance(value, int | float):
        return None
    return datetime.fromtimestamp(value / 1000, tz=UTC).isoformat()


def _str_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def parse_session(raw: object) -> LiveSession | None:
    """One session file's JSON, or None for one that is not a usable session: malformed, a
    pre-warmed spare process no one has given a task yet, or a headless one you did not open."""
    if not isinstance(raw, dict) or raw.get("spare") is True:
        return None
    if str(raw.get("entrypoint", "")).startswith("sdk"):
        return None
    pid, session_id, cwd = raw.get("pid"), raw.get("sessionId"), raw.get("cwd")
    if not isinstance(pid, int) or not isinstance(session_id, str) or not isinstance(cwd, str):
        return None
    return LiveSession(
        session_id=session_id,
        pid=pid,
        project=project_name(cwd),
        cwd=cwd,
        status=normalize_status(raw.get("status")),
        waiting_for=_str_or_none(raw.get("waitingFor")),
        name=_str_or_none(raw.get("name")),
        kind=_str_or_none(raw.get("kind")),
        status_updated_at=_iso_from_ms(raw.get("statusUpdatedAt")),
    )


def read_sessions(
    sessions_dir: Path, alive: Callable[[int, str | None], bool] | None = None
) -> list[LiveSession]:
    alive = alive or is_alive
    found: list[LiveSession] = []
    if not sessions_dir.is_dir():
        return found
    for path in sorted(sessions_dir.glob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # Claude Code rewrites these in place; a half-written one is read next tick.
            continue
        session = parse_session(raw)
        if session is not None and alive(session.pid, _str_or_none(raw.get("procStart"))):
            found.append(session)
    return found
