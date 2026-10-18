"""Pydantic data models for inputs (destinations, trip request) and outputs (itinerary)."""

from datetime import time

from pydantic import BaseModel, Field, model_validator

from src import config


def in_sri_lanka(lat: float, lng: float) -> bool:
    """True if the point is inside the Sri Lanka bounding box."""
    return (
        config.SL_MIN_LAT <= lat <= config.SL_MAX_LAT
        and config.SL_MIN_LNG <= lng <= config.SL_MAX_LNG
    )


# ---------- Inputs ----------

class Location(BaseModel):
    """Anything with an id and coordinates: a destination or the trip's start point."""

    id: str
    lat: float
    lng: float


class Destination(Location):
    """A ranked destination from Component 1. Business rules are checked in loader.py."""

    name: str
    category: str
    cost_lkr: float
    visit_duration_min: int
    opening_time: time
    closing_time: time
    score: float = Field(ge=0.0, le=1.0)


class TripRequest(BaseModel):
    """What the traveller asks for."""

    num_days: int = Field(ge=1)
    total_budget_lkr: float = Field(ge=0)
    start_lat: float
    start_lng: float
    day_start: time = config.DEFAULT_DAY_START
    day_end: time = config.DEFAULT_DAY_END

    @model_validator(mode="after")
    def check_request(self) -> "TripRequest":
        if not in_sri_lanka(self.start_lat, self.start_lng):
            raise ValueError("start point must be inside Sri Lanka")
        if self.day_end <= self.day_start:
            raise ValueError("day_end must be after day_start")
        return self


# ---------- Outputs (fields only for now) ----------

class Stop(BaseModel):
    """One visit within a day."""

    destination_id: str
    name: str
    arrival_time: time
    wait_min: float = 0.0  # waiting for the place to open; visit starts at arrival + wait
    departure_time: time
    travel_time_min: float  # from the previous stop (or start point)
    travel_cost_lkr: float
    entry_cost_lkr: float


class UnscheduledStop(BaseModel):
    """A destination that could not be placed within the trip, and why."""

    destination_id: str
    name: str
    reason: str


class DayPlan(BaseModel):
    """All stops for a single day plus its budget status."""

    day: int
    stops: list[Stop] = []
    daily_budget_lkr: float | None = None  # set by budget allocation (WBS 3.7)
    daily_cost_lkr: float = 0.0
    over_budget: bool = False


class Itinerary(BaseModel):
    """The full multi-day plan."""

    days: list[DayPlan] = []
    total_budget_lkr: float
    total_cost_lkr: float = 0.0
    over_budget: bool = False
