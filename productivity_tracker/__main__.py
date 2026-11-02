"""The server: migrate the database, then serve the API. What the container runs.

python -m productivity_tracker
"""

import uvicorn
from alembic import command
from alembic.config import Config

from productivity_tracker.api import create_app


def main() -> None:
    # Relative to the working directory, the checkout (`/app` in the image): the prod image
    # installs the package into site-packages, away from `alembic.ini`.
    command.upgrade(Config("alembic.ini"), "head")
    uvicorn.run(create_app(), host="0.0.0.0", port=8000)  # noqa: S104 - published by compose, guarded by TRACKER_TOKEN


if __name__ == "__main__":
    main()
