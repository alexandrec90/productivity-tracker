import json
import os
from pathlib import Path

import psutil
import pytest

from productivity_tracker import sessions
from productivity_tracker.sessions import (
    claude_config_dir,
    filetime_to_epoch,
    is_alive,
    parse_session,
    project_name,
    project_root,
    read_sessions,
)

# A real file Claude Code 2.1 wrote, trimmed of nothing it is read for.
RAW = {
    "pid": 2916,
    "sessionId": "9f7edbe3-4f20-4499-9ebe-1dcb13856ba2",
    "cwd": "C:\\nowhere\\productivity-tracker\\.claude\\worktrees\\zany-finding-ripple",
    "startedAt": 1793218929572,
    "procStart": "134376925277922155",
    "kind": "interactive",
    "entrypoint": "cli",
    "name": "zany-finding-ripple-5c",
    "status": "waiting",
    "waitingFor": "input needed",
    "statusUpdatedAt": 1793219855549,
    "bridgeSessionId": "session_01VdrPkCGBeAXRVw7WvysPBX",
}


def test_parse_session_reads_a_claude_code_session_file():
    session = parse_session(RAW)
    assert session is not None
    assert session.session_id == RAW["sessionId"]
    assert session.pid == 2916
    assert session.status == "waiting"
    assert session.waiting_for == "input needed"
    assert session.remote_session_id == "session_01VdrPkCGBeAXRVw7WvysPBX"
    assert session.kind == "interactive"
    assert session.status_updated_at is not None
    assert session.status_updated_at.startswith("2026-")


def test_parse_session_reads_an_unknown_status_as_idle():
    session = parse_session({**RAW, "status": "something-new"})
    assert session is not None
    assert session.status == "idle"


@pytest.mark.parametrize(
    "raw",
    [
        None,
        [],
        {**RAW, "pid": "2916"},
        {k: v for k, v in RAW.items() if k != "sessionId"},
        {k: v for k, v in RAW.items() if k != "cwd"},
        {**RAW, "spare": True},
    ],
)
def test_parse_session_rejects_what_is_not_a_usable_session(raw):
    assert parse_session(raw) is None


def test_optional_fields_may_be_missing():
    session = parse_session({"pid": 1, "sessionId": "x", "cwd": "/code/x"})
    assert session is not None
    assert session.remote_session_id is None
    assert session.waiting_for is None
    assert session.status_updated_at is None


def test_a_claude_worktree_belongs_to_its_project():
    cwd = Path("/code/devkit/.claude/worktrees/fix-ledger-5")
    assert project_root(cwd) == Path("/code/devkit")


def test_a_subdirectory_of_a_repository_belongs_to_the_repository(tmp_path):
    (tmp_path / "repo" / ".git").mkdir(parents=True)
    (tmp_path / "repo" / "src" / "pkg").mkdir(parents=True)
    assert project_root(tmp_path / "repo" / "src" / "pkg") == tmp_path / "repo"


def test_a_linked_git_worktree_belongs_to_its_main_checkout(tmp_path):
    main = tmp_path / "devkit"
    (main / ".git" / "worktrees" / "devkit-b").mkdir(parents=True)
    linked = tmp_path / "devkit-b"
    linked.mkdir()
    (linked / ".git").write_text(f"gitdir: {main.as_posix()}/.git/worktrees/devkit-b\n")
    assert project_root(linked) == main


def test_a_git_file_that_is_not_a_worktree_link_keeps_its_directory(tmp_path):
    (tmp_path / ".git").write_text("gitdir: /somewhere/else.git\n")
    assert project_root(tmp_path) == tmp_path


def test_a_directory_outside_any_repository_is_its_own_project(tmp_path):
    assert project_root(tmp_path) == tmp_path


def test_project_name_is_the_roots_name():
    assert project_name("/code/devkit/.claude/worktrees/abc") == "devkit"


def test_claude_config_dir(monkeypatch, tmp_path):
    assert claude_config_dir(tmp_path) == tmp_path
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
    assert claude_config_dir() == tmp_path / "cfg"
    monkeypatch.delenv("CLAUDE_CONFIG_DIR")
    assert claude_config_dir() == Path.home() / ".claude"


def test_filetime_to_epoch():
    # One instant, as a FILETIME (100 ns ticks since 1601) and as Unix seconds.
    assert filetime_to_epoch(134_376_925_750_000_000) == pytest.approx(1_793_218_975.0)


def test_this_process_is_alive():
    assert is_alive(os.getpid(), None)


def test_a_dead_pid_is_not_alive(monkeypatch):
    def gone(pid):
        raise psutil.NoSuchProcess(pid)

    monkeypatch.setattr(sessions.psutil, "Process", gone)
    assert not is_alive(123, None)


def test_a_recycled_pid_is_not_alive(monkeypatch):
    # procStart is a FILETIME only where Claude Code runs on Windows; pretend to be there.
    monkeypatch.setattr(sessions.sys, "platform", "win32")
    # This pid is alive, but it is not the process that started in 1601.
    assert not is_alive(os.getpid(), "1")


def test_a_pid_whose_start_matches_procstart_is_alive(monkeypatch):
    monkeypatch.setattr(sessions.sys, "platform", "win32")
    created = psutil.Process(os.getpid()).create_time()
    filetime = int((created + 11_644_473_600) * 10_000_000)
    assert is_alive(os.getpid(), str(filetime))


def test_procstart_is_ignored_off_windows(monkeypatch):
    monkeypatch.setattr(sessions.sys, "platform", "linux")
    assert is_alive(os.getpid(), "1")


def write(directory: Path, name: str, payload: object) -> None:
    (directory / name).write_text(json.dumps(payload) if not isinstance(payload, str) else payload)


def test_read_sessions_keeps_the_live_valid_ones(tmp_path):
    write(tmp_path, "1.json", {**RAW, "pid": 1, "sessionId": "live"})
    write(tmp_path, "2.json", {**RAW, "pid": 2, "sessionId": "dead"})
    write(tmp_path, "3.json", "{half-written")
    write(tmp_path, "4.json", {**RAW, "pid": 4, "spare": True})
    write(tmp_path, "4.d32cf6.key", "not json")
    seen = []

    def alive(pid, proc_start):
        seen.append((pid, proc_start))
        return pid != 2

    found = read_sessions(tmp_path, alive)

    assert [s.session_id for s in found] == ["live"]
    assert (1, RAW["procStart"]) in seen


def test_read_sessions_of_a_missing_directory_is_empty(tmp_path):
    assert read_sessions(tmp_path / "absent") == []
