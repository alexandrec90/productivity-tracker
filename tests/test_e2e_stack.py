"""End to end: the real image, the real collector, and the client the overlay uses.

The local tier (`.claude/rules/local-e2e.md`), run by `scripts/e2e.py` and deselected
everywhere else: it needs the Docker daemon. It builds and starts the compose stack under
a project of its own (`productivity-tracker-e2e`, on free ports, with
`tests/e2e-compose.yml` dropping the checkout's `.env`), so the live tracker's database
is never touched, then starts `python -m productivity_tracker.collector` against it with a
Claude config directory holding one live session and one prompt, and reads the result
back through `TrackerClient`. `down -v` removes the stack and its volume afterwards.

A machine missing what this needs fails, naming it; a skip here would read as green.
"""

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
from collections.abc import Iterator
from pathlib import Path

import pytest

from productivity_tracker.client import TrackerClient

pytestmark = pytest.mark.local

ROOT = Path(__file__).resolve().parents[1]
PROJECT = "productivity-tracker-e2e"
OVERRIDE = ROOT / "tests" / "e2e-compose.yml"
# Must match `tests/e2e-compose.yml`.
TOKEN = "e2e-token"
# The first build installs every dependency; a cached one takes seconds.
BUILD_TIMEOUT = 900
READY_TIMEOUT = 120.0
REPORT_TIMEOUT = 60.0
# Every child of a windowless scheduled run would otherwise open a console of its own.
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def free_ports(count: int) -> list[int]:
    """`count` distinct ports nothing listens on: all held open at once, so no two match."""
    sockets = [socket.socket() for _ in range(count)]
    try:
        for sock in sockets:
            sock.bind(("127.0.0.1", 0))
        return [sock.getsockname()[1] for sock in sockets]
    finally:
        for sock in sockets:
            sock.close()


class Stack:
    def __init__(self, docker: str, app_port: int, db_port: int) -> None:
        self.docker = docker
        self.url = f"http://127.0.0.1:{app_port}"
        self.env = {
            **os.environ,
            "APP_HOST_PORT": str(app_port),
            "DB_HOST_PORT": str(db_port),
            "POSTGRES_USER": "productivity_tra",
            "POSTGRES_PASSWORD": "e2e-only",  # pragma: allowlist secret - a throwaway stack's
            "POSTGRES_DB": "productivity_tracker",
        }

    def compose(self, *args: str, timeout: float = 300) -> subprocess.CompletedProcess[str]:
        command = [self.docker, "compose", "-p", PROJECT, "-f", "docker-compose.yml"]
        return subprocess.run(  # noqa: S603 - the resolved docker binary, fixed arguments
            [*command, "-f", str(OVERRIDE), *args],
            cwd=ROOT,
            env=self.env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            creationflags=NO_WINDOW,
        )

    def logs(self) -> str:
        done = self.compose("logs", "--no-color", "--tail", "60", "app")
        return done.stdout + done.stderr

    def client(self, token: str = TOKEN) -> TrackerClient:
        return TrackerClient(self.url, token)


def require_docker() -> str:
    docker = shutil.which("docker")
    if docker is None:
        pytest.fail("the local e2e tier needs the docker CLI on PATH")
    info = subprocess.run(  # noqa: S603 - the resolved docker binary, fixed arguments
        [docker, "info", "--format", "{{.ServerVersion}}"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        creationflags=NO_WINDOW,
    )
    if info.returncode != 0:
        pytest.fail(f"the Docker daemon is not running (start Docker Desktop): {info.stderr}")
    return docker


def wait_until_ready(stack: Stack) -> None:
    deadline = time.monotonic() + READY_TIMEOUT
    while time.monotonic() < deadline:
        try:
            if stack.client().request("GET", "/healthz") == {"status": "ok"}:
                return
        except (urllib.error.URLError, OSError, ValueError):
            time.sleep(1)
    pytest.fail(f"the app never answered /healthz at {stack.url}:\n{stack.logs()}")


@pytest.fixture(scope="module")
def stack() -> Iterator[Stack]:
    running = Stack(require_docker(), *free_ports(2))
    # A run killed before its teardown leaves its stack behind, on ports this run lacks.
    running.compose("down", "-v", "--remove-orphans")
    try:
        up = running.compose("up", "-d", "--build", "--wait", timeout=BUILD_TIMEOUT)
        if up.returncode != 0:
            pytest.fail(f"docker compose up failed:\n{up.stdout}\n{up.stderr}\n{running.logs()}")
        wait_until_ready(running)
        yield running
    finally:
        running.compose("down", "-v", "--remove-orphans")


def claude_dir(root: Path, pid: int) -> tuple[Path, str]:
    """A Claude config directory with one busy session of `pid`'s and one prompt, both in a
    checkout of their own: its name is the project the server files them under."""
    checkout = root / "e2e-alpha"
    (checkout / ".git").mkdir(parents=True)
    config = root / "claude"
    (config / "sessions").mkdir(parents=True)
    session = {
        "pid": pid,
        "sessionId": "e2e-session",
        "cwd": str(checkout),
        "status": "busy",
        "kind": "interactive",
        "entrypoint": "cli",
    }
    (config / "sessions" / f"{pid}.json").write_text(json.dumps(session), encoding="utf-8")
    prompt = {
        "display": "make it green",
        "timestamp": int(time.time() * 1000),
        "project": str(checkout),
        "sessionId": "e2e-session",
    }
    (config / "history.jsonl").write_text(json.dumps(prompt) + "\n", encoding="utf-8")
    return config, checkout.name


def start_collector(stack: Stack, config: Path) -> subprocess.Popen[str]:
    env = {
        **os.environ,
        # Over anything the checkout's `.env` says: an environment variable wins there.
        "TRACKER_URL": stack.url,
        "TRACKER_TOKEN": TOKEN,
        "TRACKER_TASK": "",
        "CLAUDE_CONFIG_DIR": str(config),
        "COLLECT_INTERVAL_SECONDS": "1",
    }
    return subprocess.Popen(
        [sys.executable, "-m", "productivity_tracker.collector"],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        creationflags=NO_WINDOW,
    )


def wait_for_session(client: TrackerClient, task: str) -> dict:
    deadline = time.monotonic() + REPORT_TIMEOUT
    while time.monotonic() < deadline:
        row = next(t for t in client.state()["tasks"] if t["name"] == task)
        if row["sessions"]:
            return row
        time.sleep(1)
    pytest.fail(f"the collector's session never reached task {task!r}")


def test_the_stack_refuses_a_request_without_the_token(stack):
    with pytest.raises(urllib.error.HTTPError) as refused:
        stack.client(token="").state()
    assert refused.value.code == 401


def test_a_collector_reports_its_live_session_to_the_stack(stack, tmp_path):
    client = stack.client()
    config, project = claude_dir(tmp_path, os.getpid())
    task = client.add_task(project)

    collector = start_collector(stack, config)
    try:
        row = wait_for_session(client, project)
    finally:
        collector.terminate()
        output, _ = collector.communicate(timeout=30)

    assert row["color"] == "green", output
    [session] = row["sessions"]
    assert session["session_id"] == "e2e-session"
    assert session["pid"] == os.getpid()
    assert session["host"] == socket.gethostname()
    assert row["prompts_today"] == 1
    assert client.state()["stats"]["today"]["prompts"] == 1

    assert client.set_active(task["id"], False)["color"] == "gray"
    client.remove_task(task["id"])
    assert all(t["id"] != task["id"] for t in client.state()["tasks"])


def test_a_click_reaches_the_host_that_waits_for_it(stack):
    client = stack.client()
    # Not this PC's name: a collector here would raise the window of whatever has the pid.
    client.request_focus("e2e-elsewhere", 4242)
    assert client.next_focus("e2e-elsewhere", wait=5) == 4242
    assert client.next_focus("e2e-elsewhere", wait=0) is None
