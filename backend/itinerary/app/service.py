"""What the API does, without the HTTP part: check inputs, run the optimizer, and turn its
output into the response models of app/schemas.py. app/main.py only routes requests here.

No optimizer logic lives here. The plans come from src/ unchanged:
    /itinerary   run_sequential or optimize_joint
    /reoptimize  the joint local search (src/joint.py: _evaluate, _search), started from the
                 user's edited plan instead of the sequential plan
    /validate    scheduler.validate_opening_hours and the budget module on the plan as given

Profiles: a request's profile switches config flags only while that request runs, under a
lock (two requests never see each other's flags), and restores them afterwards.
"""

import logging
import os
import random
import tempfile
import threading
import time as clock
from collections.abc import Callable, Hashable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import time
from pathlib import Path

import networkx as nx
from dotenv import dotenv_values

from app.schemas import (BudgetOut, DailyAllocation, DayCard, DayIn, ItineraryRequest, ItineraryResponse,
                         LunchIn, LunchOut, ObjectiveOut, ReoptimizeRequest, RunInfo, Status, TripSummary,
                         UnscheduledOut, ValidateRequest, ValidateResponse, VisitIn, VisitOut)
from src import config
from src.budget import OverrunReport, allocate_budget, check_overruns, cost_breakdown, day_breakdown, planned_cost
from src.distance import GoogleMatrixError, MissingApiKeyError, get_matrix_with_start
from src.graph import build_graph
from src.joint import Candidate, _evaluate, _search, optimize_joint
from src.loader import _check_rules
from src.models import DayPlan, Destination, Itinerary, MealBreak, Stop, TripRequest
from src.objective import PlanScore, score_plan
from src.pipeline import apply_budget, run_sequential
from src.routing import dijkstra
from src.scheduler import (_hhmm, _leg, day_window, living_costs, make_day_plan, schedule_days, to_minutes, to_time,
                           validate_opening_hours)

CACHE_DIR: Path = config.CACHE_DIR  # tests point this at a temporary folder
FALLBACK_CACHE_DIR = Path(tempfile.gettempdir()) / "itinerary-cache"  # read-only CACHE_DIR
NOT_IN_PLAN_REASON = "not in your edited plan; the search found no better plan that includes it"
_RUN_LOCK = threading.Lock()
log = logging.getLogger("itinerary.api")


class InputError(ValueError):
    """Bad input the optimizer cannot plan with. app/main.py turns it into a 422 response."""

    def __init__(self, errors: Sequence[tuple[str | None, str]]):
        super().__init__("; ".join(message for _, message in errors))
        self.errors = list(errors)


# ---------- Profile and travel-time source ----------

@contextmanager
def profile_flags(profile: str) -> Iterator[None]:
    """Switch on the profile's config flags for one request, then restore them."""
    overrides = config.API_PROFILES[profile]
    with _RUN_LOCK:
        old = {name: getattr(config, name) for name in overrides}
        try:
            for name, value in overrides.items():
                setattr(config, name, value)
            yield
        finally:
            for name, value in old.items():
                setattr(config, name, value)


def google_key_available() -> bool:
    """True if the server has a Google key: in its .env file, or (deployed, with
    config.API_GOOGLE_KEY_FROM_ENV on) in the environment. The key itself never leaves src/distance.py."""
    if config.API_GOOGLE_KEY_FROM_ENV and os.getenv(config.GOOGLE_API_KEY_ENV):
        return True
    env_file = config.BASE_DIR / ".env"
    return env_file.exists() and bool(dotenv_values(env_file).get(config.GOOGLE_API_KEY_ENV))


# ---------- Matrix cache folder ----------

def _writable(folder: Path) -> bool:
    """Create the folder if missing and prove a file can be written in it."""
    try:
        folder.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=folder):
            return True
    except OSError:
        return False


def cache_dir() -> Path:
    """Where this request caches travel matrices: CACHE_DIR, or a temp folder if CACHE_DIR cannot
    be written (read-only image). Checked per request, so a deleted folder is simply made again.
    The cache only saves time: on an ephemeral disk it starts empty after each restart."""
    if _writable(CACHE_DIR):
        return CACHE_DIR
    if _writable(FALLBACK_CACHE_DIR):
        log.warning("cache folder %s is not writable; using %s", CACHE_DIR, FALLBACK_CACHE_DIR)
        return FALLBACK_CACHE_DIR
    log.error("no writable cache folder (%s, %s); matrices cannot be cached", CACHE_DIR, FALLBACK_CACHE_DIR)
    return CACHE_DIR


def with_travel_source(run: Callable[[bool], object]) -> tuple[object, list[str]]:
    """run(use_google): Google when the server has a key, else (or if Google fails) offline."""
    if google_key_available():
        try:
            return run(True), []
        except (GoogleMatrixError, MissingApiKeyError, OSError) as e:
            # only the error type: a message could echo request details
            return run(False), [f"Google travel times could not be fetched ({type(e).__name__}); "
                                "used the offline estimate instead."]
    return run(False), []


def travel_source(graph: nx.DiGraph) -> str:
    """"google" if every leg is a Google road time, "estimated" if none is, else "mixed"."""
    sources = {data["source"] for _, _, data in graph.edges(data=True)}
    if sources == {"google"}:
        return "google"
    return "mixed" if "google" in sources else "estimated"


# ---------- Input checks (422) ----------

def check_destinations(destinations: Sequence[Destination]) -> None:
    """The loader's business rules, a free id per place, and START kept for the start point."""
    errors, seen = [], set()
    for i, dest in enumerate(destinations):
        field = f"destinations[{i}]"
        if dest.id == config.START_NODE_ID:
            errors.append((f"{field}.id", f"id {config.START_NODE_ID!r} is reserved for the start point"))
        if dest.id in seen:
            errors.append((f"{field}.id", f"duplicate destination id {dest.id!r}"))
        seen.add(dest.id)
        errors += [(field, f"{dest.id}: {problem}") for problem in _check_rules(dest)]
    if errors:
        raise InputError(errors)


def minimum_trip_cost(num_days: int) -> float:
    """Daily living costs no plan can avoid (food, nights, other) under the current flags."""
    return round(sum(sum(living_costs(day, num_days).values()) for day in range(1, num_days + 1)), 2)


def check_budget(trip: TripRequest) -> None:
    """Impossible budgets: zero, or below the living costs alone. Call inside profile_flags."""
    if trip.total_budget_lkr <= 0:
        raise InputError([("trip.total_budget_lkr", "must be greater than 0")])
    floor = minimum_trip_cost(trip.num_days)
    if trip.total_budget_lkr < floor:
        raise InputError([("trip.total_budget_lkr",
                           f"{trip.total_budget_lkr:,.0f} LKR is below the {floor:,.0f} LKR that food, "
                           f"accommodation and other daily costs alone need for {trip.num_days} days "
                           "(APPROX values in src/config.py)")])


# ---------- Optimizer output -> response ----------

def _leg_km(graph: nx.DiGraph, origin: Hashable, target: Hashable) -> float:
    """Road km of a leg, along the same lowest-weight path the scheduler drives."""
    path = dijkstra(graph, origin, target, config.EDGE_WEIGHTS).path
    return round(sum(graph.edges[a, b]["distance_km"] for a, b in zip(path, path[1:])), 3)


def _visit(stop: Stop, category: str, km: float) -> VisitOut:
    return VisitOut(
        destination_id=stop.destination_id, name=stop.name, category=category,
        arrival_time=stop.arrival_time, wait_min=stop.wait_min,
        visit_start=to_time(to_minutes(stop.arrival_time) + int(stop.wait_min)),
        departure_time=stop.departure_time, travel_time_min=stop.travel_time_min, travel_km=km,
        transport_mode=stop.travel_mode or "car",  # modes off = every leg by hired car (config)
        evening_drive=stop.evening_drive, travel_cost_lkr=stop.travel_cost_lkr,
        entry_cost_lkr=stop.entry_cost_lkr, cost_lkr=round(stop.travel_cost_lkr + stop.entry_cost_lkr, 2),
        score=stop.score)


def _lunch(lunch: MealBreak) -> LunchOut:
    return LunchOut(start_time=lunch.start_time, end_time=lunch.end_time, wait_min=lunch.wait_min,
                    cost_lkr=lunch.food_cost_lkr)


def day_cards(days: Sequence[DayPlan], report: OverrunReport, graph: nx.DiGraph, trip: TripRequest,
              categories: Mapping[str, str]) -> list[DayCard]:
    """One card per day. Each leg starts where the traveller is: START, then the last stop so far."""
    budgets = {d.day: d for d in report.days}
    cards, location = [], config.START_NODE_ID
    for plan in days:
        entries, km = [], 0.0
        for i, stop in enumerate(plan.stops):
            if plan.lunch is not None and plan.lunch.after_stop == i:
                entries.append(_lunch(plan.lunch))
            leg_km = _leg_km(graph, location, stop.destination_id)
            km += leg_km
            entries.append(_visit(stop, categories[stop.destination_id], leg_km))
            location = stop.destination_id
        if plan.lunch is not None and plan.lunch.after_stop == len(plan.stops):
            entries.append(_lunch(plan.lunch))
        ends = [s.departure_time for s in plan.stops] + ([plan.lunch.end_time] if plan.lunch else [])
        budget = budgets[plan.day]
        cards.append(DayCard(
            day=plan.day, start_time=trip.start_of_day(plan.day), end_time=max(ends) if ends else None,
            entries=entries, stops=len(plan.stops),
            travel_time_min=round(sum(s.travel_time_min for s in plan.stops), 2), travel_km=round(km, 3),
            cost_lkr=planned_cost(plan), cost_breakdown=day_breakdown(plan),
            allocated_lkr=budget.allocated_lkr, overrun_lkr=budget.overrun_lkr, over_budget=budget.over_budget))
    return cards


def budget_out(days: Sequence[DayPlan], report: OverrunReport) -> BudgetOut:
    """Breakdown by category and by day. The daily allocations plus the reserve add up to the total."""
    allocation = [DailyAllocation(day=d.day, allocated_lkr=d.allocated_lkr, planned_lkr=d.planned_cost_lkr,
                                  overrun_lkr=d.overrun_lkr, over_budget=d.over_budget) for d in report.days]
    trip = report.trip
    return BudgetOut(
        total_budget_lkr=trip.total_budget_lkr, planned_total_lkr=trip.total_planned_lkr,
        breakdown=cost_breakdown(days), daily_allocation=allocation, reserve_lkr=trip.reserve_lkr,
        allocated_plus_reserve_lkr=round(sum(a.allocated_lkr for a in allocation) + trip.reserve_lkr, 2),
        split_method=config.BUDGET_SPLIT_METHOD, overrun_lkr=trip.overrun_lkr, uses_reserve=trip.uses_reserve)


def status_warnings(itinerary: Itinerary, report: OverrunReport, source: str, capped: bool,
                    time_limit_s: float | None, places: int) -> list[str]:
    """Plain-language warnings, each from a real result of this plan."""
    warnings = []
    if source != "google":
        warnings.append("Travel times and distances are offline estimates (straight-line distance x "
                        f"{config.ROAD_DISTANCE_FACTOR} at APPROX road speeds), not real road data.")
    warnings.append("Transport fares, food, accommodation and other living costs are APPROX estimates "
                    "(src/config.py), not quoted prices.")
    if capped:
        warnings.append(f"The search stopped at the {time_limit_s:g} s time limit: this is the best plan "
                        "found so far. A repeat of the same request may return a different plan, because "
                        "how far the search gets depends on the server's speed.")
    trip = report.trip
    if trip.over_budget:
        warnings.append(f"The plan costs {trip.total_planned_lkr:,.0f} LKR, {trip.overrun_lkr:,.0f} LKR over "
                        f"the total budget of {trip.total_budget_lkr:,.0f} LKR.")
    elif trip.uses_reserve:
        warnings.append(f"The plan only fits by spending the {trip.reserve_lkr:,.0f} LKR reserve.")
    for day in report.days:
        if day.over_budget:
            warnings.append(f"Day {day.day} costs {day.planned_cost_lkr:,.0f} LKR, {day.overrun_lkr:,.0f} LKR "
                            f"over its allocation of {day.allocated_lkr:,.0f} LKR.")
    if itinerary.unscheduled:
        warnings.append(f"{len(itinerary.unscheduled)} of {places} places could not be scheduled; "
                        "status.unscheduled gives the reason for each.")
    return warnings


def build_response(itinerary: Itinerary, score: PlanScore, report: OverrunReport, graph: nx.DiGraph,
                   trip: TripRequest, destinations: Sequence[Destination], run: RunInfo, capped: bool,
                   start_total: float | None = None, extra_warnings: Sequence[str] = ()) -> ItineraryResponse:
    """The full /itinerary or /reoptimize response for one optimizer result."""
    categories = {d.id: d.category for d in destinations}
    cards = day_cards(itinerary.days, report, graph, trip, categories)
    source = travel_source(graph)
    conflicts = validate_opening_hours(itinerary.days, graph)  # independent re-check (0 for a planner)
    summary = TripSummary(
        days=trip.num_days, total_budget_lkr=trip.total_budget_lkr, total_cost_lkr=itinerary.total_cost_lkr,
        total_km=round(sum(c.travel_km for c in cards), 3),
        total_travel_time_min=round(sum(c.travel_time_min for c in cards), 2),
        stops=sum(c.stops for c in cards), places_requested=len(destinations),
        places_unscheduled=len(itinerary.unscheduled))
    status = Status(
        over_budget=report.trip.over_budget, days_over_budget=[d.day for d in report.days if d.over_budget],
        uses_reserve=report.trip.uses_reserve, overrun_lkr=report.trip.overrun_lkr,
        opening_hour_conflicts=conflicts,
        unscheduled=[UnscheduledOut(**u.model_dump()) for u in itinerary.unscheduled],
        search_time_capped=capped)
    warnings = [*extra_warnings,
                *status_warnings(itinerary, report, source, capped, run.time_limit_s, len(destinations))]
    if conflicts:
        warnings.append(f"{len(conflicts)} opening-hour conflicts; see status.opening_hour_conflicts.")
    return ItineraryResponse(
        travel_times=source, summary=summary, days=cards, budget=budget_out(itinerary.days, report),
        status=status, objective=ObjectiveOut(total=score.total, terms=score.breakdown["terms"],
                                              start_total=start_total),
        run=run, warnings=warnings)


def _itinerary(days: list[DayPlan], candidate: Candidate, trip: TripRequest) -> Itinerary:
    """An Itinerary from a scored joint candidate, as optimize_joint builds it."""
    return Itinerary(days=apply_budget(days, candidate.report), total_budget_lkr=trip.total_budget_lkr,
                     total_cost_lkr=candidate.report.trip.total_planned_lkr,
                     over_budget=candidate.report.trip.over_budget, unscheduled=candidate.unscheduled,
                     cost_breakdown=cost_breakdown(days))


# ---------- POST /itinerary ----------

def plan_itinerary(req: ItineraryRequest) -> ItineraryResponse:
    """A new day-by-day plan from the candidate places, by the sequential baseline or joint search."""
    check_destinations(req.destinations)
    opts = req.options
    weights = config.EVALUATION_WEIGHT_SETTINGS[opts.weights]
    with profile_flags(opts.profile):
        check_budget(req.trip)
        started = clock.perf_counter()

        def run(use_google: bool):
            if opts.method == "sequential":
                return run_sequential(req.destinations, req.trip, use_google, cache_dir(), mode_weights=weights)
            return optimize_joint(req.destinations, req.trip, weights=weights, seed=opts.seed,
                                  use_google=use_google, cache_dir=cache_dir(), time_limit_s=opts.time_limit_s)

        result, warnings = with_travel_source(run)
        runtime = round(clock.perf_counter() - started, 3)
        it, report, graph = result.itinerary, result.budget_report, result.graph
        capped, start_total = False, None
        if opts.method == "sequential":
            score = score_plan(it.days, it.unscheduled, report, weights, graph)  # with THIS weight preset
        else:
            score, capped = result.score, result.timed_out
            base = result.baseline
            start_total = score_plan(base.itinerary.days, base.itinerary.unscheduled, base.budget_report,
                                     weights, graph).total
            if not result.moves and not capped:
                warnings.append("The joint search found no plan scoring higher than the sequential plan, "
                                "so this is the sequential plan.")
        info = RunInfo(method=opts.method, profile=opts.profile, weights=opts.weights,
                       seed=opts.seed if opts.method == "joint" else None,
                       time_limit_s=opts.time_limit_s if opts.method == "joint" else None, runtime_s=runtime)
        return build_response(it, score, report, graph, req.trip, req.destinations, info, capped,
                              start_total, warnings)


# ---------- POST /reoptimize ----------

def edited_orders(req: ReoptimizeRequest) -> list[list[str]]:
    """The user's day orders with add/remove applied. Unknown or repeated ids are input errors."""
    known = {d.id for d in req.destinations}
    n = req.trip.num_days
    errors: list[tuple[str | None, str]] = []
    if len(req.day_orders) != n:
        errors.append(("day_orders", f"needs one list per day ({n}), got {len(req.day_orders)}"))
    seen: set[str] = set()
    for d, stops in enumerate(req.day_orders):
        for i, stop_id in enumerate(stops):
            if stop_id not in known:
                errors.append((f"day_orders[{d}][{i}]", f"unknown destination {stop_id!r} (not in destinations)"))
            elif stop_id in seen:
                errors.append((f"day_orders[{d}][{i}]", f"destination {stop_id!r} appears more than once"))
            seen.add(stop_id)
    removed = set(req.remove)
    errors += [(f"remove[{i}]", f"unknown destination {s!r} (not in destinations)")
               for i, s in enumerate(req.remove) if s not in known]
    for i, add in enumerate(req.add):
        if add.destination_id not in known:
            errors.append((f"add[{i}].destination_id", f"unknown destination {add.destination_id!r}"))
        elif add.destination_id in seen or add.destination_id in removed:
            errors.append((f"add[{i}].destination_id",
                           f"destination {add.destination_id!r} is already in the plan or removed"))
        seen.add(add.destination_id)
        if add.day > n:
            errors.append((f"add[{i}].day", f"day {add.day} is after the last day ({n})"))
    if errors:
        raise InputError(errors)

    orders = [[s for s in stops if s not in removed] for stops in req.day_orders]
    for i, add in enumerate(req.add):
        day = orders[add.day - 1]
        position = len(day) if add.position is None else add.position - 1
        if position > len(day):
            raise InputError([(f"add[{i}].position", f"day {add.day} has only {len(day)} stops")])
        day.insert(position, add.destination_id)
    return orders


def _start_candidate(orders, pool, reasons, graph, trip, weights, cache) -> tuple[Candidate, bool]:
    """The edited plan as the search's starting point; (candidate, repaired).

    If the plan breaks a rule as given (a stop is closed, the day runs out, ...), the greedy
    scheduler keeps the user's order but moves stops that do not fit to later days (or
    leaves them out, with the reason). Failing even that, the search starts from empty days.
    """
    start = _evaluate(orders, pool, reasons, graph, trip, weights, cache)
    if start is not None:
        return start, False
    schedule = schedule_days([config.START_NODE_ID, *(s for day in orders for s in day)], graph, trip)
    reasons.update({u.destination_id: u.reason for u in schedule.unscheduled})
    repaired = [[s.destination_id for s in d.stops] for d in schedule.days]
    left_out = [u.destination_id for u in schedule.unscheduled]
    start = _evaluate(repaired, [*pool, *left_out], reasons, graph, trip, weights, cache)
    if start is None:  # empty days always fit; every place then starts unscheduled
        everything = [*pool, *(s for day in orders for s in day)]
        for s in everything:
            reasons.setdefault(s, NOT_IN_PLAN_REASON)
        start = _evaluate([[] for _ in orders], everything, reasons, graph, trip, weights, cache)
    return start, True


def _repair_note(orders: list[list[str]], start: Candidate) -> str:
    """Which stops the repair moved to another day or left out."""
    old = {s: d for d, stops in enumerate(orders, 1) for s in stops}
    new = {s: d for d, stops in enumerate(start.day_orders, 1) for s in stops}
    changes = [f"{s} day {old[s]} -> " + (f"day {new[s]}" if s in new else "left out")
               for s in old if new.get(s) != old[s]]
    return ("Your edited plan breaks an opening-hour or day-length rule as given, so the search started "
            "from the closest feasible plan in your order" + (f" ({', '.join(changes)})." if changes else "."))


def reoptimize(req: ReoptimizeRequest) -> ItineraryResponse:
    """Improve the user's edited plan by the joint local search, starting from that plan."""
    check_destinations(req.destinations)
    orders = edited_orders(req)
    removed = set(req.remove)
    destinations = [d for d in req.destinations if d.id not in removed]
    opts = req.options
    weights = config.EVALUATION_WEIGHT_SETTINGS[opts.weights]
    with profile_flags(opts.profile):
        check_budget(req.trip)
        started = clock.perf_counter()

        def run(use_google: bool):
            matrix = get_matrix_with_start(destinations, req.trip, use_google=use_google, cache_dir=cache_dir())
            graph = build_graph(destinations, matrix, req.trip, mode_weights=weights)
            in_plan = {s for day in orders for s in day}
            pool = [d.id for d in destinations if d.id not in in_plan]
            reasons = {s: NOT_IN_PLAN_REASON for s in pool}
            cache: dict = {}
            start, repaired = _start_candidate(orders, pool, reasons, graph, req.trip, weights, cache)
            # one restart only: a random restart would throw the user's order away
            best, _moves, _stats, timed_out = _search(
                start, reasons, graph, req.trip, weights, config.JOINT_MAX_ITERATIONS, config.JOINT_USE_ANNEALING,
                random.Random(opts.seed), cache, 0, config.JOINT_USE_BLOCK_MOVES, deadline)
            return graph, start, repaired, best, timed_out

        deadline = started + opts.time_limit_s
        (graph, start, repaired, best, capped), warnings = with_travel_source(run)
        runtime = round(clock.perf_counter() - started, 3)
        if repaired:
            warnings.insert(0, _repair_note(orders, start))
        final = {s for day in best.day_orders for s in day}
        warnings += [f"{a.destination_id}, which you added, was left out: "
                     + next(u.reason for u in best.unscheduled if u.destination_id == a.destination_id)
                     for a in req.add if a.destination_id not in final]
        info = RunInfo(method="joint (from your plan)", profile=opts.profile, weights=opts.weights,
                       seed=opts.seed, time_limit_s=opts.time_limit_s, runtime_s=runtime)
        return build_response(_itinerary(best.days, best, req.trip), best.score, best.report, graph, req.trip,
                              destinations, info, capped, start.score.total, warnings)


# ---------- POST /validate ----------

def _check_days(req: ValidateRequest) -> None:
    """One entry per trip day, numbered 1..num_days, and only known places, each at most once."""
    n, errors = req.trip.num_days, []
    if sorted(d.day for d in req.days) != list(range(1, n + 1)):
        errors.append(("days", f"needs exactly one entry per day 1..{n}, got days {[d.day for d in req.days]}"))
    known, seen = {d.id for d in req.destinations}, set()
    for d, day in enumerate(req.days):
        for i, entry in enumerate(day.entries):
            field = f"days[{d}].entries[{i}]"
            if isinstance(entry, VisitIn):
                if entry.destination_id not in known:
                    errors.append((f"{field}.destination_id",
                                   f"unknown destination {entry.destination_id!r} (not in destinations)"))
                elif entry.destination_id in seen:
                    errors.append((f"{field}.destination_id",
                                   f"destination {entry.destination_id!r} appears more than once"))
                seen.add(entry.destination_id)
                if to_minutes(entry.departure_time) < to_minutes(entry.arrival_time) + entry.wait_min:
                    errors.append((f"{field}.departure_time", "departure is before arrival + wait"))
            elif entry.end_time <= entry.start_time:
                errors.append((f"{field}.end_time", "lunch must end after it starts"))
    if errors:
        raise InputError(errors)


def _validate_day(day: DayIn, graph: nx.DiGraph, trip: TripRequest, location: Hashable, prev_end: int | None,
                  cache: dict) -> tuple[DayPlan, list[str], Hashable, int]:
    """Rebuild one day as given (times untouched) and list its timing conflicts.

    Returns (day plan, conflicts, where the day ends, when its activity ends). An evening
    drive into the first stop is allowed by the scheduler's own rule (scheduler.day_window).
    """
    window = day_window(trip, day.day, prev_end)
    window_start, window_end = window.start, window.end
    stops, lunch, conflicts = [], None, []
    free = window_start  # when the traveller is free again (last departure or lunch end)
    for entry in day.entries:
        start = to_minutes(entry.start_time if isinstance(entry, LunchIn) else entry.arrival_time)
        if isinstance(entry, LunchIn):
            if start < free:
                before = "the previous activity ends" if stops else "the day starts"
                conflicts.append(f"day {day.day}: lunch starts {entry.start_time:%H:%M}, before "
                                 f"{before} ({_hhmm(free)})")
            lunch = MealBreak(after_stop=len(stops), free_time=to_time(min(free, start)),
                              wait_min=max(0, start - free), start_time=entry.start_time, end_time=entry.end_time,
                              food_cost_lkr=config.LUNCH_COST_LKR if config.USE_LUNCH_BREAK else 0.0)
            free = to_minutes(entry.end_time)
            continue
        node = graph.nodes[entry.destination_id]
        leg = _leg(graph, location, entry.destination_id, config.EDGE_WEIGHTS, cache)
        earliest = free + leg.duration_min
        evening = not stops and lunch is None and leg.duration_min <= window.evening_min
        label = f"day {day.day}, {entry.destination_id}"
        if start < earliest and not (evening and start >= window_start):
            conflicts.append(f"{label}: arrives {entry.arrival_time:%H:%M}, but the {leg.duration_min} min "
                             f"trip there cannot arrive before {_hhmm(earliest)}")
        if start < window_start:
            conflicts.append(f"{label}: arrives {entry.arrival_time:%H:%M}, before the day starts "
                             f"({_hhmm(window_start)})")
        if to_minutes(entry.departure_time) > window_end:
            conflicts.append(f"{label}: leaves {entry.departure_time:%H:%M}, after the day ends "
                             f"({_hhmm(window_end)})")
        stops.append(Stop(destination_id=entry.destination_id, name=node["name"], arrival_time=entry.arrival_time,
                          wait_min=entry.wait_min, departure_time=entry.departure_time,
                          travel_time_min=leg.duration_min, travel_cost_lkr=leg.cost_lkr,
                          entry_cost_lkr=node["cost_lkr"], score=node["score"], travel_mode=leg.mode,
                          evening_drive=evening and start < earliest))
        free, location = to_minutes(entry.departure_time), entry.destination_id
    return make_day_plan(day.day, stops, lunch, trip.num_days), conflicts, location, free


def validate_plan(req: ValidateRequest) -> ValidateResponse:
    """Check a plan for opening-hour, timing and budget problems without changing it."""
    check_destinations(req.destinations)
    _check_days(req)
    opts = req.options
    weights = config.EVALUATION_WEIGHT_SETTINGS[opts.weights]
    with profile_flags(opts.profile):

        def run(use_google: bool):
            matrix = get_matrix_with_start(req.destinations, req.trip, use_google=use_google, cache_dir=cache_dir())
            return build_graph(req.destinations, matrix, req.trip, mode_weights=weights)

        graph, warnings = with_travel_source(run)
        days, timing, location, prev_end, cache = [], [], config.START_NODE_ID, None, {}
        for day in sorted(req.days, key=lambda d: d.day):
            plan, conflicts, location, prev_end = _validate_day(day, graph, req.trip, location, prev_end, cache)
            days.append(plan)
            timing += conflicts
        report = check_overruns(days, allocate_budget(days, req.trip))
        hours = validate_opening_hours(days, graph)
        source = travel_source(graph)
        if source != "google":
            warnings.append("Travel times are offline estimates, so the timing check is APPROX.")
        warnings.append("Costs are recomputed by the optimizer's rules (APPROX rates in src/config.py); "
                        "any costs sent with the plan are ignored.")
        over_days = [d.day for d in report.days if d.over_budget]
        return ValidateResponse(
            valid=not hours and not timing and not report.trip.over_budget, travel_times=source,
            opening_hour_conflicts=hours, timing_conflicts=timing, budget=budget_out(days, report),
            days_over_budget=over_days, over_budget=report.trip.over_budget, profile=opts.profile,
            warnings=warnings)
