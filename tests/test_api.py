"""The API end to end against Postgres: snapshots in, task rows and colours out."""

from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from productivity_tracker.api import create_app, token_matches
from productivity_tracker.config import Settings


def session(session_id: str, project: str = "alpha", status: str = "busy", **extra: Any):
    return {
        "session_id": session_id,
        "pid": 100,
        "project": project,
        "cwd": f"C:/code/{project}",
        "status": status,
        "waiting_for": None,
        "name": f"{project}-{session_id}",
        "kind": "interactive",
        "remote_session_id": f"session_{session_id}",
        "status_updated_at": "2026-10-28T12:00:00+00:00",
        **extra,
    }


def report(api: TestClient, host: str, *sessions: dict[str, Any]) -> None:
    response = api.post("/snapshots", json={"host": host, "sessions": list(sessions)})
    assert response.status_code == 204, response.text


def tasks(api: TestClient) -> dict[str, dict[str, Any]]:
    response = api.get("/state")
    assert response.status_code == 200, response.text
    return {t["name"]: t for t in response.json()["tasks"]}


def test_a_busy_session_makes_its_task_green(api):
    report(api, "desk", session("s1"))

    alpha = tasks(api)["alpha"]
    assert alpha["color"] == "green"
    assert alpha["active"] is True
    [only] = alpha["sessions"]
    assert only["host"] == "desk"
    assert only["remote_session_id"] == "session_s1"


def test_sessions_on_two_pcs_share_one_row_and_a_question_turns_it_yellow(api):
    report(api, "desk", session("s1", status="busy"))
    report(api, "laptop", session("s2", status="waiting", waiting_for="input needed"))

    alpha = tasks(api)["alpha"]
    assert alpha["color"] == "yellow"
    assert {s["host"] for s in alpha["sessions"]} == {"desk", "laptop"}


def test_a_task_whose_sessions_are_all_idle_is_red(api):
    report(api, "desk", session("s1", status="idle"))

    assert tasks(api)["alpha"]["color"] == "red"


def test_a_session_missing_from_the_next_snapshot_has_ended(api):
    report(api, "desk", session("s1"), session("s2", project="beta"))
    report(api, "desk", session("s2", project="beta"))

    state = tasks(api)
    # The task outlives its last session, and with no agent it is red.
    assert state["alpha"]["sessions"] == []
    assert state["alpha"]["color"] == "red"
    assert state["beta"]["color"] == "green"


def test_a_snapshot_only_replaces_its_own_hosts_sessions(api):
    report(api, "desk", session("s1"))
    report(api, "laptop")

    assert len(tasks(api)["alpha"]["sessions"]) == 1


def test_a_pc_that_stopped_reporting_no_longer_counts(api, sync_db: Engine):
    report(api, "desk", session("s1"))
    with sync_db.begin() as conn:
        conn.execute(text("UPDATE hosts SET last_seen_at = now() - interval '1 hour'"))

    alpha = tasks(api)["alpha"]
    assert alpha["sessions"] == []
    assert alpha["color"] == "red"


def test_a_repeated_session_id_in_one_snapshot_is_stored_once(api):
    report(api, "desk", session("s1", status="idle"), session("s1", status="busy"))

    [only] = tasks(api)["alpha"]["sessions"]
    assert only["status"] == "busy"


def test_an_inactive_task_is_gray_and_listed_after_the_active_ones(api):
    report(api, "desk", session("s1", project="alpha"), session("s2", project="beta"))
    alpha_id = tasks(api)["alpha"]["id"]

    response = api.put(f"/tasks/{alpha_id}/active", json={"active": False})
    assert response.status_code == 200
    assert response.json()["color"] == "gray"

    listed = api.get("/state").json()["tasks"]
    assert [t["name"] for t in listed] == ["beta", "alpha"]
    assert listed[1]["color"] == "gray"
    # Its sessions are still there for a click to cycle through.
    assert len(listed[1]["sessions"]) == 1


def test_reactivating_a_task_restores_its_colour(api):
    report(api, "desk", session("s1", status="waiting"))
    alpha_id = tasks(api)["alpha"]["id"]
    api.put(f"/tasks/{alpha_id}/active", json={"active": False})
    api.put(f"/tasks/{alpha_id}/active", json={"active": True})

    assert tasks(api)["alpha"]["color"] == "yellow"


def test_toggling_an_unknown_task_is_404(api):
    assert api.put("/tasks/999/active", json={"active": False}).status_code == 404


def test_an_unknown_status_is_rejected(api):
    response = api.post(
        "/snapshots", json={"host": "desk", "sessions": [session("s1", status="asleep")]}
    )
    assert response.status_code == 422


@pytest.mark.parametrize("header", [None, "Bearer wrong", "test-token"])
def test_requests_without_the_token_are_refused(api, header):
    headers = {"Authorization": header} if header else {}
    api.headers.pop("Authorization")
    assert api.get("/state", headers=headers).status_code == 401
    assert (
        api.post("/snapshots", json={"host": "x", "sessions": []}, headers=headers).status_code
        == 401
    )


def test_healthz_needs_no_token(api):
    api.headers.pop("Authorization")
    assert api.get("/healthz").json() == {"status": "ok"}


def test_a_server_without_a_token_asks_for_none(sync_db, test_database_url):
    app = create_app(Settings(database_url=test_database_url, tracker_token=""))
    with TestClient(app) as client:
        assert client.post("/snapshots", json={"host": "desk", "sessions": []}).status_code == 204
        assert client.get("/state").json()["tasks"] == []


def test_prompts_reported_by_a_pc_show_on_their_row_and_the_scoreboard(api):
    now = datetime.now(UTC).isoformat()
    prompt = {"session_id": "s1", "at": now, "project": "alpha"}
    body = {"host": "desk", "sessions": [session("s1")], "prompts": [prompt]}
    # Sent twice, as a restarted collector would.
    assert api.post("/snapshots", json=body).status_code == 204
    assert api.post("/snapshots", json=body).status_code == 204

    state = api.get("/state").json()
    assert state["tasks"][0]["prompts_today"] == 1
    assert state["stats"]["today"]["prompts"] == 1
    assert state["stats"]["today"]["peak_busy"] == 1
    assert state["stats"]["streak"] == 1


def test_a_server_with_an_unknown_timezone_refuses_to_start(sync_db, test_database_url):
    app = create_app(Settings(database_url=test_database_url, tracker_timezone="Mars/Olympus"))
    with pytest.raises(ValueError, match="TRACKER_TIMEZONE"), TestClient(app):
        pass


@pytest.mark.parametrize(
    ("expected", "header", "ok"),
    [
        ("", None, True),
        ("", "Bearer anything", True),
        ("s3cret", "Bearer s3cret", True),
        ("s3cret", "bearer s3cret", True),
        ("s3cret", "Bearer nope", False),
        ("s3cret", "s3cret", False),
        ("s3cret", None, False),
    ],
)
def test_token_matches(expected, header, ok):
    assert token_matches(expected, header) is ok
