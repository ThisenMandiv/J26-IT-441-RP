"""Request and response models of the HTTP API (the JSON contract, see docs/API.md).

Inputs reuse the optimizer's own models: Destination is exactly the Component 1 record and
TripRequest is the trip form, so the API and the optimizer can never disagree on them.
Outputs are shaped for the Trips screens: a trip summary, one card per day (visits and
lunch in time order), the budget by category and by day, status flags and warnings.
Every number in a response comes from the optimizer's output (app/service.py).
"""

from datetime import time
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from src import config
from src.models import Destination, TripRequest

Profile = Literal["realistic", "basic"]
WeightsPreset = Literal["default", "budget", "time"]
Method = Literal["joint", "sequential"]
TravelTimes = Literal["estimated", "google", "mixed"]


# ---------- Requests ----------

class PlanOptions(BaseModel):
    """Options shared by /itinerary and /reoptimize."""

    profile: Profile = config.API_DEFAULT_PROFILE  # "realistic" = every v5 rule on
    weights: WeightsPreset = "default"  # config.EVALUATION_WEIGHT_SETTINGS
    seed: int = config.JOINT_SEED
    time_limit_s: float = Field(config.API_JOINT_TIME_LIMIT_S, gt=0, le=config.API_MAX_TIME_LIMIT_S)


class ItineraryOptions(PlanOptions):
    method: Method = "joint"


class ItineraryRequest(BaseModel):
    trip: TripRequest
    destinations: list[Destination] = Field(min_length=1)  # ranked places from Component 1
    options: ItineraryOptions = ItineraryOptions()


class AddStop(BaseModel):
    destination_id: str
    day: int = Field(ge=1)
    position: int | None = Field(None, ge=1)  # 1 = first stop of the day; None = end of the day


class ReoptimizeRequest(BaseModel):
    """The user's edited plan. The search starts from day_orders after add/remove are applied."""

    trip: TripRequest
    destinations: list[Destination] = Field(min_length=1)
    day_orders: list[list[str]]  # destination ids per day, in visiting order
    add: list[AddStop] = []
    remove: list[str] = []  # removed for good: the search will not put these back
    options: PlanOptions = PlanOptions()


class VisitIn(BaseModel):
    type: Literal["visit"]
    destination_id: str
    arrival_time: time
    wait_min: float = Field(0.0, ge=0)
    departure_time: time


class LunchIn(BaseModel):
    type: Literal["lunch"]
    start_time: time
    end_time: time


EntryIn = Annotated[VisitIn | LunchIn, Field(discriminator="type")]


class DayIn(BaseModel):
    """One day of a plan to validate. A DayCard from /itinerary fits here unchanged."""

    day: int = Field(ge=1)
    entries: list[EntryIn] = []


class ValidateOptions(BaseModel):
    profile: Profile = config.API_DEFAULT_PROFILE
    weights: WeightsPreset = "default"  # only picks the transport mode per leg (realistic profile)


class ValidateRequest(BaseModel):
    trip: TripRequest
    destinations: list[Destination] = Field(min_length=1)
    days: list[DayIn]
    options: ValidateOptions = ValidateOptions()


# ---------- Responses ----------

class VisitOut(BaseModel):
    type: Literal["visit"] = "visit"
    destination_id: str
    name: str
    category: str
    arrival_time: time
    wait_min: float  # waiting for the place to open
    visit_start: time
    departure_time: time
    travel_time_min: float  # from the previous stop (or the start point / last night's stop)
    travel_km: float
    transport_mode: str  # "car", "bus", "walk", or e.g. "car+bus" via a stopover
    evening_drive: bool  # this leg was driven the evening before
    travel_cost_lkr: float
    entry_cost_lkr: float
    cost_lkr: float  # travel + entry
    score: float  # Component 1 score


class LunchOut(BaseModel):
    type: Literal["lunch"] = "lunch"
    start_time: time
    end_time: time
    wait_min: float  # idle time before lunch (counted as waiting by the objective)
    cost_lkr: float


Entry = Annotated[VisitOut | LunchOut, Field(discriminator="type")]


class DayCard(BaseModel):
    day: int
    start_time: time
    end_time: time | None  # end of the day's last activity; None when the day is empty
    entries: list[Entry]  # visits and lunch, in time order
    stops: int
    travel_time_min: float
    travel_km: float
    cost_lkr: float  # everything planned for this day (the five categories added up)
    cost_breakdown: dict[str, float]
    allocated_lkr: float
    overrun_lkr: float
    over_budget: bool


class TripSummary(BaseModel):
    days: int
    total_budget_lkr: float
    total_cost_lkr: float
    total_km: float
    total_travel_time_min: float
    stops: int
    places_requested: int
    places_unscheduled: int


class DailyAllocation(BaseModel):
    day: int
    allocated_lkr: float
    planned_lkr: float
    overrun_lkr: float
    over_budget: bool


class BudgetOut(BaseModel):
    """Daily allocations + reserve_lkr = total_budget_lkr (allocated_plus_reserve_lkr shows it)."""

    total_budget_lkr: float
    planned_total_lkr: float
    breakdown: dict[str, float]  # accommodation, transport, food, activities, other
    daily_allocation: list[DailyAllocation]
    reserve_lkr: float
    allocated_plus_reserve_lkr: float
    split_method: str
    overrun_lkr: float  # planned minus total budget, 0 when it fits
    uses_reserve: bool


class UnscheduledOut(BaseModel):
    destination_id: str
    name: str
    reason: str


class Status(BaseModel):
    over_budget: bool  # the whole trip costs more than the total budget
    days_over_budget: list[int]
    uses_reserve: bool
    overrun_lkr: float
    opening_hour_conflicts: list[str]  # independent re-check of every visit; empty = none
    unscheduled: list[UnscheduledOut]
    search_time_capped: bool  # the joint search hit time_limit_s and returned its best plan so far


class ObjectiveOut(BaseModel):
    total: float  # higher is better
    terms: dict[str, float]
    # joint: the sequential plan's score; reoptimize: the edited plan's score; sequential: None
    start_total: float | None = None


class RunInfo(BaseModel):
    method: str
    profile: str
    weights: str
    seed: int | None
    time_limit_s: float | None
    runtime_s: float


class ItineraryResponse(BaseModel):
    travel_times: TravelTimes
    summary: TripSummary
    days: list[DayCard]
    budget: BudgetOut
    status: Status
    objective: ObjectiveOut
    run: RunInfo
    warnings: list[str]


class ValidateResponse(BaseModel):
    valid: bool  # no conflicts of any kind and the trip fits the total budget
    travel_times: TravelTimes
    opening_hour_conflicts: list[str]
    timing_conflicts: list[str]  # arrivals that the travel time makes impossible, overlaps, day window
    budget: BudgetOut
    days_over_budget: list[int]
    over_budget: bool
    profile: str
    warnings: list[str]


class ErrorItem(BaseModel):
    field: str | None  # e.g. "trip.day_end" or "destinations[2].closing_time"
    message: str


class ErrorResponse(BaseModel):
    detail: list[ErrorItem]
