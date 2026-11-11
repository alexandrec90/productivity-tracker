"""Settings shared by the server, the collector and the overlay, read from the environment.

Every PC runs the collector, one PC runs the server, and the laptop runs the overlay, so
each process reads only the fields it needs; the rest keep their defaults.
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    # The checkout's `.env` as well as the working directory's: the overlay is started from
    # a shortcut, whose working directory is anywhere. A later file wins.
    model_config = SettingsConfigDict(env_file=(REPO_ROOT / ".env", ".env"), extra="ignore")

    # Server: where the state lives.
    database_url: str = ""
    # A host whose collector has not reported for this long is treated as offline, and its
    # sessions stop counting: a PC that went to sleep must not leave a task green.
    stale_after_seconds: float = 30.0
    # Where your day starts and ends, for prompts per day, records and streaks: an IANA name
    # Postgres knows, e.g. "America/New_York".
    tracker_timezone: str = "UTC"

    # Collector and overlay: where the server is. Every request carries the token as a
    # bearer header; the server checks it only when its own copy is set.
    tracker_url: str = "http://127.0.0.1:8003"
    tracker_token: str = ""

    # Collector: set on a PC whose sessions are all one task (e.g. "itopia"), and every
    # session there reports under that name instead of its project's, so none of them
    # lights a project row. Unset, each session's task is its project.
    tracker_task: str = ""

    # Overlay: what you connect to in Remote Desktop, by host, for any PC whose address there
    # is not its own name (an IP, say): the window to look for and what to open if there is
    # none. JSON, e.g. {"DESKTOP-B9FC8VP": "100.76.121.58"}.
    tracker_rdp_targets: dict[str, str] = {}

    collect_interval_seconds: float = 3.0
    poll_interval_seconds: float = 2.0
    # Claude Code's config directory, holding `sessions/<pid>.json`. Unset means the one
    # Claude Code itself uses: `$CLAUDE_CONFIG_DIR`, else `~/.claude`.
    claude_config_dir: Path | None = None
