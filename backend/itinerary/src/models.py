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
    # Version 5. Defaults = the old behaviour: the same start every day, no evening drives.
    day_starts: list[time] | None = None  # one start time per day (e.g. 05:30 for a hike day)
    evening_drive_limit_min: int | None = Field(default=None, ge=0)  # None: see config.USE_EVENING_DRIVE

    @model_validator(mode="after")
    def check_request(self) -> "TripRequest":
        if not in_sri_lanka(self.start_lat, self.start_lng):
            raise ValueError("start point must be inside Sri Lanka")
        if self.day_end <= self.day_start:
            raise ValueError("day_end must be after day_start")
        if self.day_starts is not None:
            if len(self.day_starts) != self.num_days:
                raise ValueError(f"day_starts needs one time per day ({self.num_days}), got {len(self.day_starts)}")
            if any(start >= self.day_end for start in self.day_starts):
                raise ValueError("every day start must be before day_end")
        return self

    def start_of_day(self, day: int) -> time:
        """Start time of day `day` (1-based)."""
        return self.day_start if self.day_starts is None else self.day_starts[day - 1]

    def evening_limit_min(self) -> int:
        """Longest evening drive allowed after day_end (0 = none)."""
        if self.evening_drive_limit_min is not None:
            return self.evening_drive_limit_min
        return config.EVENING_DRIVE_LIMIT_MIN if config.USE_EVENING_DRIVE else 0


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
    score: float = 0.0  # destination score from Component 1, used by the objective
    travel_mode: str | None = None  # "car", "bus", "walk" (or "car+bus" via a stopover); None = modes off
    # True: this leg was driven the evening before (first stop of a day); the traveller is
    # at the place when the day starts, so arrival_time is the day's start time.
    evening_drive: bool = False


class UnscheduledStop(BaseModel):
    """A destination that could not be placed within the trip, and why."""

    destination_id: str
    name: str
    reason: str


class MealBreak(BaseModel):
    """A non-destination stop: the lunch break (config.USE_LUNCH_BREAK)."""

    kind: str = "lunch"
    after_stop: int  # destination stops before it in the day (0 = before the first stop)
    free_time: time  # when the traveller was free for it
    wait_min: float = 0.0  # idle from free_time until the lunch window opened
    start_time: time
    end_time: time
    food_cost_lkr: float


class DayPlan(BaseModel):
    """All stops for a single day plus its budget status."""

    day: int
    stops: list[Stop] = []
    lunch: MealBreak | None = None  # only with config.USE_LUNCH_BREAK on
    # Daily living costs (config.USE_DAILY_COSTS; all 0 when off). Lunch's cost is in `lunch`.
    food_cost_lkr: float = 0.0
    accommodation_cost_lkr: float = 0.0  # the night after this day
    other_cost_lkr: float = 0.0
    daily_budget_lkr: float | None = None  # set by budget allocation (WBS 3.7)
    daily_cost_lkr: float = 0.0
    over_budget: bool = False


class Itinerary(BaseModel):
    """The full multi-day plan."""

    days: list[DayPlan] = []
    total_budget_lkr: float
    total_cost_lkr: float = 0.0
    over_budget: bool = False
    unscheduled: list[UnscheduledStop] = []
    # planned cost per category: accommodation, transport, food, activities, other (budget.cost_breakdown)
    cost_breakdown: dict[str, float] = {}
