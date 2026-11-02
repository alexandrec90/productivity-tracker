"""Fixtures for the API tests: a throwaway `<db>_test` database next to DATABASE_URL's.

The API tests never touch DATABASE_URL's own database: they create `<name>_test` beside
it, migrate it with `alembic upgrade head` (so the migrations are exercised too), and
truncate it before each test. Running them against the PC that hosts the live tracker
cannot wipe its tasks.
"""

import asyncio
import os
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, make_url, text
from sqlalchemy.exc import OperationalError

from productivity_tracker.api import create_app
from productivity_tracker.config import Settings

ROOT = Path(__file__).resolve().parents[1]
TOKEN = "test-token"

if sys.platform == "win32":
    # psycopg's async driver cannot run on the Proactor loop Windows defaults to. The server
    # itself runs in a Linux container; this is only for a local test run on Windows.
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@pytest.fixture(scope="session")
def test_database_url() -> Iterator[str]:
    base = os.environ.get("DATABASE_URL") or Settings().database_url
    if not base:
        pytest.fail("DATABASE_URL is not set: the API tests need Postgres (see .env.example)")
    url = make_url(base)
    name = f"{url.database}_test"
    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
            conn.execute(text(f'CREATE DATABASE "{name}"'))
    except OperationalError as exc:
        pytest.fail(
            f"Postgres at DATABASE_URL is unreachable ({exc.orig}): docker compose up -d db"
        )
    finally:
        admin.dispose()
    test_url = url.set(database=name).render_as_string(hide_password=False)
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("DATABASE_URL", test_url)
        command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
    yield test_url


@pytest.fixture
def sync_db(test_database_url: str) -> Iterator[Engine]:
    engine = create_engine(test_database_url)
    with engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE agent_sessions, hosts, tasks, prompts, daily_activity"
                " RESTART IDENTITY CASCADE"
            )
        )
    yield engine
    engine.dispose()


@pytest.fixture
def api(sync_db: Engine, test_database_url: str) -> Iterator[TestClient]:
    settings = Settings(database_url=test_database_url, tracker_token=TOKEN, stale_after_seconds=30)
    with TestClient(create_app(settings), headers={"Authorization": f"Bearer {TOKEN}"}) as client:
        yield client
