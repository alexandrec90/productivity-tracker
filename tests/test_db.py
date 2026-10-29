"""The models and the migrations describe the same schema."""

import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Engine
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


def test_the_migrated_database_matches_the_models(sync_db: Engine):
    with sync_db.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []


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
