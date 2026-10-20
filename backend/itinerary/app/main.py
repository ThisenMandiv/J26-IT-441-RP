"""FastAPI app: the HTTP layer of the itinerary optimizer (Component 2).

    uvicorn app.main:app --reload        (from backend/itinerary, see docs/API.md)

    GET  /health       is the service up, and where travel times will come from
    POST /itinerary    candidate places + trip -> day-by-day plan
    POST /reoptimize   the user's edited plan -> improved plan, searched from that plan
    POST /validate     a plan as it stands -> opening-hour, timing and budget problems

This file only routes: app/service.py does the work. Every error is returned as
{"detail": [{"field": ..., "message": ...}]}: 422 for bad input, 401 for a missing or wrong
X-API-Key (only if the server sets API_KEY), 413 for a body over the size limit, 500 (with no
stack trace or internal detail) for anything unexpected. Deployment: see docs/DEPLOY.md.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app import security, service
from app.schemas import (ErrorResponse, ItineraryRequest, ItineraryResponse, ReoptimizeRequest,
                         ValidateRequest, ValidateResponse)
from src import config

log = logging.getLogger("itinerary.api")
startup_log = logging.getLogger("uvicorn.error")  # uvicorn prints this logger at INFO level
ERRORS = {code: {"model": ErrorResponse} for code in (401, 413, 422, 500)}
PROTECTED = [Depends(security.require_api_key)]  # /health stays open


def startup_message() -> str:
    """One line for the server log: which settings are on. Never prints a secret, only "set"."""
    google = "present" if service.google_key_available() else "not set (offline travel estimates)"
    auth = "required" if security.api_key() else "not required"
    origins = ", ".join(security.allowed_origins()) or "none"
    return (f"itinerary API starting: Google Maps key {google}; default profile "
            f"{config.API_DEFAULT_PROFILE}; X-API-Key {auth}; CORS origins: {origins}")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    startup_log.info(startup_message())
    yield


app = FastAPI(title="Itinerary optimizer (Component 2)", version="1.0", lifespan=lifespan,
              description="Budget-aware multi-day itinerary optimizer. All travel times are offline "
                          "estimates unless the server has a Google key; all costs are APPROX.")
security.install_middleware(app)


# ---------- Errors ----------

def _errors(items, status: int) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": [{"field": f, "message": m} for f, m in items]})


def _field(loc) -> str | None:
    """Pydantic's location ("body", "trip", "day_end") as "trip.day_end"; list indexes as [i]."""
    parts = [p for p in loc if p != "body"]
    text = ""
    for p in parts:
        text += f"[{p}]" if isinstance(p, int) else (f".{p}" if text else str(p))
    return text or None


def _message(error: dict) -> str:
    """Pydantic's message without its "Value error, " prefix."""
    return error["msg"].removeprefix("Value error, ")


def _item(error: dict) -> tuple[str | None, str]:
    if error["type"] == "json_invalid":  # its location is a character offset, not a field
        return None, "request body is not valid JSON"
    return _field(error["loc"]), _message(error)


@app.exception_handler(RequestValidationError)
async def invalid_request(_request: Request, exc: RequestValidationError) -> JSONResponse:
    return _errors([_item(e) for e in exc.errors()], 422)


@app.exception_handler(service.InputError)
async def input_error(_request: Request, exc: service.InputError) -> JSONResponse:
    return _errors(exc.errors, 422)


@app.exception_handler(security.Unauthorized)
async def unauthorized(_request: Request, exc: security.Unauthorized) -> JSONResponse:
    return _errors([(security.API_KEY_HEADER, str(exc))], 401)


@app.exception_handler(Exception)
async def unexpected(_request: Request, exc: Exception) -> JSONResponse:
    log.exception("unexpected error")  # the trace goes to the server log only, never to the client
    return _errors([(None, "internal error: the request could not be planned")], 500)


# ---------- Endpoints ----------

@app.get("/health")
def health() -> dict:
    return {"status": "ok",
            "travel_times": "google" if service.google_key_available() else "estimated",
            "default_profile": config.API_DEFAULT_PROFILE,
            "profiles": sorted(config.API_PROFILES)}


@app.post("/itinerary", response_model=ItineraryResponse, responses=ERRORS, dependencies=PROTECTED)
def itinerary(req: ItineraryRequest) -> ItineraryResponse:
    return service.plan_itinerary(req)


@app.post("/reoptimize", response_model=ItineraryResponse, responses=ERRORS, dependencies=PROTECTED)
def reoptimize(req: ReoptimizeRequest) -> ItineraryResponse:
    return service.reoptimize(req)


@app.post("/validate", response_model=ValidateResponse, responses=ERRORS, dependencies=PROTECTED)
def validate(req: ValidateRequest) -> ValidateResponse:
    return service.validate_plan(req)
