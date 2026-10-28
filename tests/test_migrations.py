"""The migration scripts `alembic.ini` points at load, with no database.

The first PR Gate on `main` failed at `alembic upgrade head` with "Path doesn't exist:
migrations": the generator wrote `alembic.ini` and no `migrations/` folder. A broken
script directory fails here, in the suite, before the gate's database step.
"""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

ROOT = Path(__file__).resolve().parents[1]


def scripts() -> ScriptDirectory:
    return ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))


def test_the_script_directory_loads():
    directory = scripts()
    assert (Path(directory.dir) / "env.py").is_file()
    assert (Path(directory.dir) / "script.py.mako").is_file()


def test_the_revisions_have_at_most_one_head():
    # Two heads make `alembic upgrade head` refuse: two branches each added a revision.
    assert len(scripts().get_heads()) <= 1
