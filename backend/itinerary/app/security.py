"""Deployment safety for the HTTP API: the shared API key, CORS and the request size limit.

Settings come from environment variables only (see docs/DEPLOY.md), read when they are needed,
so a host can change them without a code change:
    API_KEY          optional shared secret; if set, POST endpoints need it in X-API-Key
    ALLOWED_ORIGINS  comma-separated browser origins allowed by CORS; unset = none
(GOOGLE_MAPS_API_KEY is handled by app/service.py and src/distance.py.)
No secret is ever logged or returned; the startup log only says whether one is set.
"""

import hmac
import os

from fastapi import FastAPI, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader

from src import config

API_KEY_ENV = "API_KEY"
ALLOWED_ORIGINS_ENV = "ALLOWED_ORIGINS"
API_KEY_HEADER = "X-API-Key"


class Unauthorized(Exception):
    """Missing or wrong X-API-Key. app/main.py turns it into a 401 response."""


# ---------- Settings from the environment ----------

def api_key() -> str | None:
    """The shared secret, or None if the server does not require one."""
    return os.getenv(API_KEY_ENV) or None


def allowed_origins() -> list[str]:
    """ALLOWED_ORIGINS as a list: "https://a.lk, https://b.lk/" -> ["https://a.lk", "https://b.lk"]."""
    raw = os.getenv(ALLOWED_ORIGINS_ENV, "")
    return [origin.strip().rstrip("/") for origin in raw.split(",") if origin.strip()]


# ---------- Shared API key ----------

# auto_error=False: the check below decides, so the API works with no key set
_key_header = APIKeyHeader(name=API_KEY_HEADER, auto_error=False,
                           description="Needed only if the server sets API_KEY.")


def require_api_key(given: str | None = Security(_key_header)) -> None:
    """Endpoint dependency: pass if no API_KEY is set, else the header must match it."""
    expected = api_key()
    if expected is None:
        return
    if not given:
        raise Unauthorized(f"missing {API_KEY_HEADER} header: this server requires an API key")
    if not hmac.compare_digest(given.encode(), expected.encode()):  # constant time: no timing hints
        raise Unauthorized(f"{API_KEY_HEADER} is not valid")


# ---------- Request body size limit ----------

def _too_large() -> JSONResponse:
    message = f"request body is too large: at most {config.API_MAX_BODY_BYTES} bytes"
    return JSONResponse(status_code=413, content={"detail": [{"field": None, "message": message}]})


class BodySizeLimit:
    """ASGI middleware: answer 413 if a body is over config.API_MAX_BODY_BYTES.

    Checks the declared Content-Length first, then counts the bytes actually received (a
    chunked upload has no Content-Length). The body is buffered, at most the limit, and then
    handed to the app unchanged.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = config.API_MAX_BODY_BYTES
        declared = dict(scope["headers"]).get(b"content-length", b"")
        if declared.isdigit() and int(declared) > limit:
            await _too_large()(scope, receive, send)
            return

        messages, size = [], 0
        while True:
            message = await receive()
            messages.append(message)
            if message["type"] != "http.request":  # client went away
                break
            size += len(message.get("body", b""))
            if size > limit:
                await _too_large()(scope, receive, send)
                return
            if not message.get("more_body", False):
                break

        async def replay():
            return messages.pop(0) if messages else await receive()

        await self.app(scope, replay, send)


# ---------- Install ----------

def install_middleware(app: FastAPI) -> None:
    """Body size limit, then CORS around it (so a 413 still carries CORS headers)."""
    app.add_middleware(BodySizeLimit)
    origins = allowed_origins()
    if origins:  # no origins: no CORS headers, browsers on other sites are blocked
        app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST"],
                           allow_headers=["Content-Type", API_KEY_HEADER])
