import json
import os
from pathlib import Path

import pytest

from productivity_tracker.prompts import Prompt, PromptFeed, parse_prompt, read_prompts

NOON_MS = 1_793_188_800_000  # 2026-10-28T12:00:00Z


def line(display: str = "fix the bug", ms: int = NOON_MS, session: str | None = "s1", **extra):
    raw = {"display": display, "pastedContents": {}, "timestamp": ms, "project": "/code/alpha"}
    if session is not None:
        raw["sessionId"] = session
    return {**raw, **extra}


def by_name(cwd: str) -> str:
    return Path(cwd).name


def write(path: Path, *entries: dict) -> None:
    path.write_text("".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8")


def test_a_prompt_keeps_when_and_where_but_not_what():
    prompt = parse_prompt(line(), by_name)
    assert prompt == Prompt(session_id="s1", at="2026-10-28T12:00:00+00:00", project="alpha")


def test_the_project_is_the_sessions_project(tmp_path):
    # The default lookup folds a worktree into its repository, as for sessions.
    raw = line(project=str(tmp_path / "alpha" / ".claude" / "worktrees" / "w1"))
    assert parse_prompt(raw).project == "alpha"


def test_a_prompt_from_an_old_claude_without_a_session_still_counts():
    assert parse_prompt(line(session=None), by_name).session_id == ""


@pytest.mark.parametrize("display", ["/clear", "  /model", "!git status", "", "   "])
def test_commands_and_blank_lines_are_not_prompts(display):
    assert parse_prompt(line(display), by_name) is None


@pytest.mark.parametrize(
    "raw",
    [
        None,
        [],
        line(timestamp="noon"),
        line(timestamp=True),
        line(project=""),
        line(project=None),
        {**line(), "display": None},
    ],
)
def test_malformed_lines_are_skipped(raw):
    assert parse_prompt(raw, by_name) is None


def test_read_prompts_skips_a_half_written_line(tmp_path):
    path = tmp_path / "history.jsonl"
    path.write_text(json.dumps(line()) + "\n" + '{"display": "half', encoding="utf-8")
    assert [p.session_id for p in read_prompts(path, by_name)] == ["s1"]


def test_read_prompts_of_a_missing_file_is_empty(tmp_path):
    assert read_prompts(tmp_path / "history.jsonl") == []


def test_the_feed_holds_prompts_until_delivered(tmp_path):
    path = tmp_path / "history.jsonl"
    write(path, line(ms=NOON_MS), line(ms=NOON_MS + 1000))
    feed = PromptFeed(path)

    first = feed.pending()
    assert len(first) == 2
    # Not delivered (the post failed): offered again.
    assert feed.pending() == first
    feed.delivered(first)
    assert feed.pending() == []


def test_the_feed_sends_its_history_in_batches(tmp_path):
    path = tmp_path / "history.jsonl"
    write(path, *(line(ms=NOON_MS + i) for i in range(5)))
    feed = PromptFeed(path, batch=2)

    sent = []
    while batch := feed.pending():
        sent.extend(batch)
        feed.delivered(batch)
    assert len(sent) == 5
    assert len(set(sent)) == 5


def test_the_feed_offers_only_what_was_appended_since(tmp_path):
    path = tmp_path / "history.jsonl"
    write(path, line(ms=NOON_MS))
    feed = PromptFeed(path)
    feed.delivered(feed.pending())

    write(path, line(ms=NOON_MS), line(ms=NOON_MS + 5000, session="s2"))
    # A different size is enough for the feed to notice; the time stamp may not move.
    os.utime(path, ns=(1, 1))

    assert [p.session_id for p in feed.pending()] == ["s2"]


def test_the_feed_without_a_history_file_has_nothing(tmp_path):
    assert PromptFeed(tmp_path / "history.jsonl").pending() == []
