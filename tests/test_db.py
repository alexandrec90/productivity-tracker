"""The models and the migrations describe the same schema."""

from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Engine, text
from sqlalchemy.ext.asyncio import AsyncEngine

from productivity_tracker.db import (
    AgentSession,
    Base,
    DailyActivity,
    Host,
    Prompt,
    Task,
    make_engine,
)

ROOT = Path(__file__).resolve().parents[1]


def test_the_migrated_database_matches_the_models(sync_db: Engine):
    with sync_db.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []


def test_the_list_migration_clears_stray_rows_keeps_real_ones_and_adds_itopia(
    sync_db: Engine, test_database_url: str, monkeypatch
):
    monkeypatch.setenv("DATABASE_URL", test_database_url)
    config = Config(str(ROOT / "alembic.ini"))
    command.downgrade(config, "0002")
    try:
        with sync_db.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO tasks (name) VALUES"
                    " ('ann'), ('tmpbg7zdsvw'), ('vs-code'), ('devkit')"
                )
            )
            conn.execute(text("INSERT INTO hosts (name, last_seen_at) VALUES ('desk', now())"))
            conn.execute(
                text(
                    "INSERT INTO agent_sessions"
                    " (host, session_id, task_id, pid, cwd, status, remote_session_id)"
                    " SELECT 'desk', name, id, 1, '/x', 'idle', 'session_x' FROM tasks"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO prompts (host, session_id, at, project)"
                    " VALUES ('desk', 's', now(), 'devkit')"
                )
            )
    finally:
        command.upgrade(config, "head")

    with sync_db.connect() as conn:
        rows: dict[str, bool] = dict(conn.execute(text("SELECT name, active FROM tasks")).all())
        sessions: dict[str, bool] = dict(
            conn.execute(text("SELECT session_id, task_id IS NOT NULL FROM agent_sessions")).all()
        )
        dispatched = conn.execute(text("SELECT dispatched FROM prompts")).scalar_one()
    assert rows == {"devkit": True, "itopia": False}
    # A stray row's session outlives it, unassigned; the next report rewrites it anyway.
    assert sessions == {"ann": False, "tmpbg7zdsvw": False, "vs-code": False, "devkit": True}
    assert dispatched is False


def test_the_models_are_the_five_tables():
    models = (Task, Host, AgentSession, Prompt, DailyActivity)
    assert {m.__tablename__ for m in models} == set(Base.metadata.tables)


def test_make_engine_needs_a_url():
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        make_engine("")


def test_make_engine_is_async():
    engine = make_engine("postgresql+psycopg://u:p@localhost:1/db")
    assert isinstance(engine, AsyncEngine)
    assert engine.url.database == "db"
