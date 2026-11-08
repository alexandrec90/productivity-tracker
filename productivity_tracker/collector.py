"""Run on every PC: report this PC's live Claude Code sessions to the server every few seconds.

Each report is the PC's whole picture, so a session that ended simply stops appearing, and
a PC that stops reporting goes stale on the server instead of staying green. It also carries
any prompts typed since the last report (their time and project, never their text), which
the server turns into daily counts, records and streaks.

It is also the overlay's hand on this PC: a click on one of this PC's sessions reaches it
through the server, and it brings that session's terminal forward. That only works from
inside the desktop you see, so start it at login, not as a service.

    pt-collector            # or: python -m productivity_tracker.collector
"""

import logging
import socket
import threading
import time
import urllib.error
from collections.abc import Callable
from dataclasses import asdict, replace
from typing import Any

from productivity_tracker.client import TrackerClient
from productivity_tracker.config import Settings
from productivity_tracker.focus import focus_local
from productivity_tracker.prompts import Prompt, PromptFeed
from productivity_tracker.sessions import LiveSession, claude_config_dir, read_sessions

log = logging.getLogger("productivity_tracker.collector")

# A click often comes just as its Remote Desktop window reconnects, and a disconnected
# desktop has no foreground to take, so it is tried for about this long.
FOCUS_ATTEMPTS = 15
FOCUS_RETRY_SECONDS = 1.0


def build_snapshot(
    host: str, sessions: list[LiveSession], prompts: list[Prompt] | None = None
) -> dict[str, Any]:
    return {
        "host": host,
        "sessions": [asdict(s) for s in sessions],
        "prompts": [asdict(p) for p in prompts or []],
    }


def assign_task[T: (LiveSession, Prompt)](items: list[T], task: str) -> list[T]:
    """Every session or prompt under `task`, for a PC that is one task as a whole; unchanged
    when `task` is empty."""
    task = task.strip()
    return [replace(item, project=task) for item in items] if task else items


def prompt_feed(settings: Settings) -> PromptFeed:
    return PromptFeed(claude_config_dir(settings.claude_config_dir) / "history.jsonl")


def collect_once(settings: Settings, client: TrackerClient, host: str, feed: PromptFeed) -> int:
    """One report: the live sessions, and the prompts the server has not had yet. Those count
    as delivered only once the post succeeds."""
    prompts = feed.pending()
    sessions = [
        s
        for s in read_sessions(claude_config_dir(settings.claude_config_dir) / "sessions")
        if s.session_id not in feed.dispatched_sessions
    ]
    sessions = assign_task(sessions, settings.tracker_task)
    client.post_snapshot(
        build_snapshot(host, sessions, assign_task(prompts, settings.tracker_task))
    )
    feed.delivered(prompts)
    return len(sessions)


def focus_with_retries(
    pid: int,
    focus: Callable[[int], bool] = focus_local,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    for attempt in range(FOCUS_ATTEMPTS):
        if attempt:
            sleep(FOCUS_RETRY_SECONDS)
        if focus(pid):
            return True
    log.warning("no window could be raised for pid %s", pid)
    return False


def serve_focus_once(
    client: TrackerClient,
    host: str,
    focus: Callable[[int], bool] = focus_with_retries,
) -> None:
    """Wait for one click on this PC's sessions, and carry it out."""
    pid = client.next_focus(host)
    if pid is not None:
        focus(pid)


def serve_focus(client: TrackerClient, host: str, retry_seconds: float) -> None:
    """Carry out clicks for as long as the collector runs. On a thread of its own: the wait
    lasts until the next click, and the reports cannot."""
    while True:
        try:
            serve_focus_once(client, host)
        except (urllib.error.URLError, OSError, ValueError):
            # The report loop already says when the server is unreachable.
            time.sleep(retry_seconds)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = Settings()
    client = TrackerClient(settings.tracker_url, settings.tracker_token)
    feed = prompt_feed(settings)
    host = socket.gethostname()
    log.info(
        "reporting %s's sessions to %s%s",
        host,
        settings.tracker_url,
        f" as task {settings.tracker_task!r}" if settings.tracker_task else "",
    )
    threading.Thread(
        target=serve_focus,
        args=(client, host, settings.collect_interval_seconds),
        daemon=True,
    ).start()
    reachable = True
    while True:
        try:
            collect_once(settings, client, host, feed)
            if not reachable:
                log.info("server reachable again")
            reachable = True
        except (urllib.error.URLError, OSError, ValueError) as exc:
            # Logged once per outage, not once per tick: the server being down for an hour
            # is one event.
            if reachable:
                log.warning("cannot reach %s: %s", settings.tracker_url, exc)
            reachable = False
        time.sleep(settings.collect_interval_seconds)


if __name__ == "__main__":
    main()
