import json
import logging

import pytest

from productivity_tracker import collector
from productivity_tracker.collector import assign_task, build_snapshot, collect_once, prompt_feed
from productivity_tracker.config import Settings
from productivity_tracker.prompts import Prompt
from productivity_tracker.sessions import LiveSession


def live(session_id: str = "s1") -> LiveSession:
    return LiveSession(
        session_id=session_id,
        pid=1,
        project="alpha",
        cwd="/code/alpha",
        status="busy",
        waiting_for=None,
        name=None,
        kind="interactive",
        remote_session_id="session_x",
        status_updated_at=None,
    )


def test_build_snapshot_is_the_apis_body():
    assert build_snapshot("desk", [live()]) == {
        "host": "desk",
        "sessions": [
            {
                "session_id": "s1",
                "pid": 1,
                "project": "alpha",
                "cwd": "/code/alpha",
                "status": "busy",
                "waiting_for": None,
                "name": None,
                "kind": "interactive",
                "remote_session_id": "session_x",
                "status_updated_at": None,
            }
        ],
        "prompts": [],
    }


def test_build_snapshot_carries_the_prompts():
    prompt = Prompt(session_id="s1", at="2026-10-28T12:00:00+00:00", project="alpha")
    assert build_snapshot("desk", [], [prompt])["prompts"] == [
        {"session_id": "s1", "at": "2026-10-28T12:00:00+00:00", "project": "alpha"}
    ]


class FakeClient:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.posted: list[dict] = []

    def post_snapshot(self, snapshot: dict) -> None:
        if self.fail:
            raise OSError("refused")
        self.posted.append(snapshot)


def settings(tmp_path, **extra) -> Settings:
    return Settings(claude_config_dir=tmp_path, **extra)


def history(tmp_path, *entries: dict) -> None:
    (tmp_path / "history.jsonl").write_text(
        "".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8"
    )


def typed(ms: int, project: str = "/code/roguelike") -> dict:
    return {"display": "go", "timestamp": ms, "project": project, "sessionId": "s1"}


def test_collect_once_reports_the_config_dirs_sessions(tmp_path, monkeypatch):
    (tmp_path / "sessions").mkdir()
    (tmp_path / "sessions" / "1.json").write_text(
        json.dumps({"pid": 1, "sessionId": "s1", "cwd": str(tmp_path), "status": "busy"})
    )
    # pid 1 is no process of ours; the liveness check has its own tests.
    monkeypatch.setattr("productivity_tracker.sessions.is_alive", lambda pid, start: True)
    client = FakeClient()

    count = collect_once(settings(tmp_path), client, "desk", prompt_feed(settings(tmp_path)))

    assert count == 1
    [snapshot] = client.posted
    assert snapshot["host"] == "desk"
    assert snapshot["sessions"][0]["session_id"] == "s1"
    assert snapshot["sessions"][0]["project"] == tmp_path.name


def test_collect_once_sends_each_prompt_once(tmp_path):
    history(tmp_path, typed(1_000), typed(2_000))
    feed = prompt_feed(settings(tmp_path))
    client = FakeClient()

    collect_once(settings(tmp_path), client, "desk", feed)
    collect_once(settings(tmp_path), client, "desk", feed)

    assert [len(s["prompts"]) for s in client.posted] == [2, 0]
    assert client.posted[0]["prompts"][0]["project"] == "roguelike"


def test_prompts_of_a_failed_report_go_in_the_next_one(tmp_path):
    history(tmp_path, typed(1_000))
    feed = prompt_feed(settings(tmp_path))

    with pytest.raises(OSError):
        collect_once(settings(tmp_path), FakeClient(fail=True), "desk", feed)
    client = FakeClient()
    collect_once(settings(tmp_path), client, "desk", feed)

    assert len(client.posted[0]["prompts"]) == 1


def test_assign_task_puts_every_session_under_the_pcs_task():
    sessions = [live("s1"), live("s2")]
    assert [s.project for s in assign_task(sessions, " itopia ")] == ["itopia", "itopia"]
    # The rest of each session is untouched: a click still finds it by host and pid.
    assert assign_task(sessions, "itopia")[0].cwd == "/code/alpha"


def test_assign_task_without_a_task_keeps_each_project():
    sessions = [live()]
    assert assign_task(sessions, "") == sessions
    assert assign_task(sessions, "   ") == sessions


def test_collect_once_on_a_whole_pc_task_reports_under_it(tmp_path, monkeypatch):
    (tmp_path / "sessions").mkdir()
    (tmp_path / "sessions" / "1.json").write_text(
        json.dumps({"pid": 1, "sessionId": "s1", "cwd": "/code/roguelike", "status": "busy"})
    )
    history(tmp_path, typed(1_000))
    monkeypatch.setattr("productivity_tracker.sessions.is_alive", lambda pid, start: True)
    client = FakeClient()
    pc = settings(tmp_path, tracker_task="itopia")

    collect_once(pc, client, "itopia-pc", prompt_feed(pc))

    assert client.posted[0]["sessions"][0]["project"] == "itopia"
    assert client.posted[0]["prompts"][0]["project"] == "itopia"


def test_assign_task_also_moves_prompts():
    prompt = Prompt(session_id="s1", at="2026-10-28T12:00:00+00:00", project="alpha")
    assert assign_task([prompt], "itopia")[0].project == "itopia"


class Stop(Exception):
    pass


def test_main_keeps_reporting_and_logs_an_outage_once(tmp_path, monkeypatch, caplog):
    outcomes = iter([None, OSError("refused"), OSError("refused"), None])

    class Client:
        def __init__(self, url, token):
            pass

        def post_snapshot(self, snapshot):
            outcome = next(outcomes)
            if outcome is not None:
                raise outcome

    ticks = iter(range(3))

    def sleep(seconds):
        if next(ticks, None) is None:
            raise Stop

    caplog.set_level(logging.INFO)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(collector, "TrackerClient", Client)
    monkeypatch.setattr(collector.time, "sleep", sleep)

    with pytest.raises(Stop):
        collector.main()

    messages = [r.getMessage() for r in caplog.records]
    assert sum("cannot reach" in m for m in messages) == 1
    assert any("reachable again" in m for m in messages)


def test_collect_once_with_no_sessions_still_reports(tmp_path):
    client = FakeClient()
    assert collect_once(settings(tmp_path), client, "desk", prompt_feed(settings(tmp_path))) == 0
    assert client.posted == [{"host": "desk", "sessions": [], "prompts": []}]
