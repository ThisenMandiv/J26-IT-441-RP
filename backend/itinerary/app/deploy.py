"""Entry point for a deployed server (the Docker image runs uvicorn app.deploy:app).

The same app as app/main.py, with one difference: the Google key may also come from the
GOOGLE_MAPS_API_KEY environment variable, because hosts such as Render and Cloud Run pass
secrets that way and have no .env file. Locally (uvicorn app.main:app) only .env counts.
"""

from src import config

config.API_GOOGLE_KEY_FROM_ENV = True

from app.main import app  # noqa: E402

__all__ = ["app"]
