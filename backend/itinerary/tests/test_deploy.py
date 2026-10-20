"""Tests for deployment settings: API key, request limits, CORS, cache folder, Google key
from the environment, startup log, and the Docker files (app/security.py, app/deploy.py).

Inputs are the 15 MOCK places of data/destinations.json. Google is off (no network in tests).
"""

import importlib
import json
import logging
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import main, security, service
from app.main import app
from src import config

KANDY = {"start_lat": 7.2906, "start_lng": 80.6337}
POSTS = ("/itinerary", "/reoptimize", "/validate")
ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A client with Google off, a private matrix cache and no API_KEY / ALLOWED_ORIGINS."""
    monkeypatch.setattr(service, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(service, "google_key_available", lambda: False)
    monkeypatch.delenv(security.API_KEY_ENV, raising=False)
    monkeypatch.delenv(security.ALLOWED_ORIGINS_ENV, raising=False)
    return TestClient(app)


@pytest.fixture(scope="module")
def places() -> list[dict]:
    return json.loads(config.DESTINATIONS_FILE.read_text(encoding="utf-8"))


def small_trip(places) -> dict:
    """A quick 1-day sequential plan of 3 MOCK places."""
    return {"trip": {"num_days": 1, "total_budget_lkr": 50_000, **KANDY},
            "destinations": places[:3], "options": {"method": "sequential", "profile": "basic"}}


def many(places, n) -> list[dict]:
    """n distinct places: the MOCK records copied with new ids."""
    return [{**places[i % len(places)], "id": f"X{i:03d}"} for i in range(n)]


def messages(response) -> list[str]:
    return [item["message"] for item in response.json()["detail"]]


# ---------- 1. Shared API key (X-API-Key) ----------

def test_no_api_key_set_means_open(client, places):
    assert client.post("/itinerary", json=small_trip(places)).status_code == 200


@pytest.mark.parametrize("path", POSTS)
def test_missing_key_is_401_when_set(client, monkeypatch, path):
    monkeypatch.setenv(security.API_KEY_ENV, "s3cret")
    r = client.post(path, json={})
    assert r.status_code == 401
    assert r.json() == {"detail": [{"field": "X-API-Key",
                                    "message": "missing X-API-Key header: this server requires an API key"}]}


@pytest.mark.parametrize("path", POSTS)
def test_wrong_key_is_401_and_not_echoed(client, monkeypatch, path):
    monkeypatch.setenv(security.API_KEY_ENV, "s3cret")
    r = client.post(path, json={}, headers={"X-API-Key": "guess"})
    assert r.status_code == 401
    assert messages(r) == ["X-API-Key is not valid"]
    assert "s3cret" not in r.text and "guess" not in r.text


@pytest.mark.parametrize("path", POSTS)
def test_right_key_passes_to_validation(client, monkeypatch, path):
    monkeypatch.setenv(security.API_KEY_ENV, "s3cret")
    r = client.post(path, json={}, headers={"X-API-Key": "s3cret"})
    assert r.status_code == 422  # past the key check, stopped by the empty body


def test_right_key_plans(client, monkeypatch, places):
    monkeypatch.setenv(security.API_KEY_ENV, "s3cret")
    r = client.post("/itinerary", json=small_trip(places), headers={"X-API-Key": "s3cret"})
    assert r.status_code == 200, r.text


def test_health_stays_open(client, monkeypatch):
    monkeypatch.setenv(security.API_KEY_ENV, "s3cret")
    assert client.get("/health").status_code == 200


def test_key_is_checked_before_the_body(client, monkeypatch):
    """No key + bad body: the caller learns nothing about the body rules."""
    monkeypatch.setenv(security.API_KEY_ENV, "s3cret")
    assert client.post("/itinerary", content=b"not json").status_code == 401


# ---------- 2. Request limits ----------

@pytest.mark.parametrize("path", POSTS)
def test_too_many_destinations_is_422(client, places, path):
    n = config.API_MAX_DESTINATIONS + 1
    r = client.post(path, json={"trip": {"num_days": 1, "total_budget_lkr": 1, **KANDY},
                                "destinations": many(places, n)})
    assert r.status_code == 422
    expected = f"too many destinations: at most {config.API_MAX_DESTINATIONS} per request, got {n}"
    assert {"field": "destinations", "message": expected} in r.json()["detail"]


def test_destination_cap_is_inclusive(client, places):
    body = small_trip(places)
    body["destinations"] = many(places, config.API_MAX_DESTINATIONS)
    body["trip"]["total_budget_lkr"] = 0  # rejected later, by the budget rule, not by the cap
    r = client.post("/itinerary", json=body)
    assert not any("too many destinations" in m for m in messages(r))


def test_destination_cap_is_in_the_openapi_schema(client):
    schema = client.get("/openapi.json").json()["components"]["schemas"]["ItineraryRequest"]
    assert schema["properties"]["destinations"]["maxItems"] == config.API_MAX_DESTINATIONS


def test_big_body_is_413(client):
    r = client.post("/itinerary", content=b" " * (config.API_MAX_BODY_BYTES + 1),
                    headers={"Content-Type": "application/json"})
    assert r.status_code == 413
    assert messages(r) == [f"request body is too large: at most {config.API_MAX_BODY_BYTES} bytes"]


def test_big_chunked_body_is_413(client):
    """No Content-Length (chunked upload): the bytes received are counted."""
    def chunks():
        for _ in range(config.API_MAX_BODY_BYTES // 1024 + 2):
            yield b" " * 1024

    r = client.post("/itinerary", content=chunks(), headers={"Content-Type": "application/json"})
    assert r.status_code == 413


def test_body_at_the_limit_reaches_the_app(client, monkeypatch, places):
    body = json.dumps(small_trip(places)).encode()
    monkeypatch.setattr(config, "API_MAX_BODY_BYTES", len(body))
    r = client.post("/itinerary", content=body, headers={"Content-Type": "application/json"})
    assert r.status_code == 200, r.text


# ---------- 3. CORS (ALLOWED_ORIGINS) ----------

def test_allowed_origins_parsing(monkeypatch):
    monkeypatch.setenv(security.ALLOWED_ORIGINS_ENV, " https://a.lk/ ,, https://b.lk ")
    assert security.allowed_origins() == ["https://a.lk", "https://b.lk"]
    monkeypatch.delenv(security.ALLOWED_ORIGINS_ENV)
    assert security.allowed_origins() == []


def tiny_app() -> TestClient:
    app_ = FastAPI()
    app_.get("/ping")(lambda: {"ok": True})
    security.install_middleware(app_)
    return TestClient(app_)


def test_cors_allows_only_listed_origins(monkeypatch):
    monkeypatch.setenv(security.ALLOWED_ORIGINS_ENV, "https://a.lk")
    c = tiny_app()
    ok = c.get("/ping", headers={"Origin": "https://a.lk"})
    assert ok.headers["access-control-allow-origin"] == "https://a.lk"
    other = c.get("/ping", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in other.headers
    preflight = c.options("/ping", headers={"Origin": "https://a.lk", "Access-Control-Request-Method": "POST",
                                            "Access-Control-Request-Headers": "X-API-Key"})
    assert preflight.status_code == 200


def test_no_origins_means_no_cors_headers(monkeypatch):
    monkeypatch.delenv(security.ALLOWED_ORIGINS_ENV, raising=False)
    r = tiny_app().get("/ping", headers={"Origin": "https://a.lk"})
    assert "access-control-allow-origin" not in r.headers


# ---------- 4. Cache folder ----------

def test_missing_cache_folder_is_created(client, places, tmp_path):
    folder = tmp_path / "cache"
    assert not folder.exists()
    assert client.post("/itinerary", json=small_trip(places)).status_code == 200
    assert any(folder.iterdir())


def test_cache_folder_deleted_between_requests(client, places, tmp_path):
    import shutil
    assert client.post("/itinerary", json=small_trip(places)).status_code == 200
    shutil.rmtree(tmp_path / "cache")
    assert client.post("/itinerary", json=small_trip(places)).status_code == 200


def test_unwritable_cache_falls_back_to_temp(client, places, tmp_path, monkeypatch):
    blocker = tmp_path / "file"  # a file where the folder should be: mkdir fails, as on a read-only disk
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setattr(service, "CACHE_DIR", blocker / "cache")
    monkeypatch.setattr(service, "FALLBACK_CACHE_DIR", tmp_path / "fallback")
    assert service.cache_dir() == tmp_path / "fallback"
    assert client.post("/itinerary", json=small_trip(places)).status_code == 200
    assert any((tmp_path / "fallback").iterdir())


# ---------- 5. Google key from the environment (deployed only) ----------

def test_env_key_counts_only_with_the_deploy_flag(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)  # no .env file
    monkeypatch.setenv(config.GOOGLE_API_KEY_ENV, "from-the-environment")
    monkeypatch.setattr(config, "API_GOOGLE_KEY_FROM_ENV", False)
    assert service.google_key_available() is False
    monkeypatch.setattr(config, "API_GOOGLE_KEY_FROM_ENV", True)
    assert service.google_key_available() is True
    monkeypatch.setenv(config.GOOGLE_API_KEY_ENV, "")
    assert service.google_key_available() is False


def test_deploy_entry_point_turns_the_flag_on(monkeypatch):
    monkeypatch.setattr(config, "API_GOOGLE_KEY_FROM_ENV", False)  # restored after the test
    import app.deploy
    importlib.reload(app.deploy)
    assert config.API_GOOGLE_KEY_FROM_ENV is True
    assert app.deploy.app is main.app


def test_flag_is_off_by_default():
    assert config.API_GOOGLE_KEY_FROM_ENV is False


# ---------- 6. Startup log ----------

def test_startup_log_says_key_present_without_printing_it(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    monkeypatch.setattr(config, "API_GOOGLE_KEY_FROM_ENV", True)
    monkeypatch.setenv(config.GOOGLE_API_KEY_ENV, "AIza-super-secret")
    monkeypatch.setenv(security.API_KEY_ENV, "shared-secret")
    monkeypatch.setenv(security.ALLOWED_ORIGINS_ENV, "https://a.lk")
    caplog.set_level(logging.INFO, logger="uvicorn.error")
    with TestClient(app):  # runs the lifespan startup
        pass
    text = caplog.text
    assert "Google Maps key present" in text
    assert f"default profile {config.API_DEFAULT_PROFILE}" in text
    assert "X-API-Key required" in text and "CORS origins: https://a.lk" in text
    assert "AIza-super-secret" not in text and "shared-secret" not in text


def test_startup_log_without_key(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    monkeypatch.delenv(config.GOOGLE_API_KEY_ENV, raising=False)
    monkeypatch.delenv(security.API_KEY_ENV, raising=False)
    line = main.startup_message()
    assert "Google Maps key not set (offline travel estimates)" in line
    assert "X-API-Key not required" in line


# ---------- 7. Docker files ----------

def test_dockerignore_excludes_secrets_and_bulk():
    lines = (ROOT / ".dockerignore").read_text(encoding="utf-8").split()
    for entry in ("venv", "data/results", "tests", ".env", "__pycache__"):
        assert entry in lines or f"{entry}/" in lines or f"**/{entry}" in lines, entry


def test_dockerfile_uses_port_and_deploy_entry():
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "python:3.13-slim" in text and "requirements.txt" in text
    assert "app.deploy:app" in text and "${PORT" in text
