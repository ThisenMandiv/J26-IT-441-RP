"""Greedy day scheduling with opening-hours checks (WBS 3.6).

schedule_days() walks the TSP visit order and fills one day at a time:
- the day starts at day_start where the traveller slept: START on day 1,
  otherwise the last stop of the previous day (the trip is an open path)
- a stop is added only if, after travelling there, it is open for the whole
  visit and the visit ends by day_end
- closed on arrival but opening soon (wait <= MAX_WAIT_MIN) -> wait for it
- opening later than that -> skip it for now and retry it after each
  stop placed later the same day (it may be open by then)
- any other problem -> defer it to the next day
- still unplaced after num_days -> unscheduled, with the last reason

Times are whole minutes since midnight inside this module. Travel times are
rounded UP to the next minute, so the plan never promises an earlier arrival.

Version 5 (behind config flags, off by default):
- lunch break (USE_LUNCH_BREAK): attempt() wraps every stop check with the lunch rule
  described in config.py, and close_day() adds lunch after a day's last stop. The greedy
  scheduler, schedule_fixed (joint), the naive baseline and the exact benchmark all go
  through attempt(), so they follow exactly the same rule.
- per-day start times (TripRequest.day_starts) and evening drives (USE_EVENING_DRIVE or
  TripRequest.evening_drive_limit_min): day_window() gives each day's start, end and how
  long an evening drive into it may be; attempt() tries the evening drive only when the
  morning drive makes the day's first stop infeasible.
"""

import math
from collections.abc import Callable, Hashable, Mapping, Sequence
from datetime import time
from typing import NamedTuple

import networkx as nx

from src import config
from src.models import DayPlan, MealBreak, Stop, TripRequest, UnscheduledStop
from src.routing import dijkstra

Weights = Mapping[str, float]

# Reasons a stop is not placed. EARLY ones are retried later the same day.
EARLY = "early"
CLOSED = "closed"
DAY_END = "day_end"


class ScheduleResult(NamedTuple):
    days: list[DayPlan]
    unscheduled: list[UnscheduledStop]


class Leg(NamedTuple):
    duration_min: int  # rounded up
    cost_lkr: float
    mode: str | None = None  # transport mode(s) of the path; None when modes are off


class Attempt(NamedTuple):
    ok: bool
    kind: str | None  # None when ok, else EARLY / CLOSED / DAY_END
    reason: str
    arrival: int = 0
    wait: int = 0
    departure: int = 0
    leg: Leg | None = None
    lunch: tuple[int, int] | None = None  # (free from, lunch start) when lunch comes before this stop
    evening: bool = False  # the leg was driven the evening before (first stop of a day)


class DayWindow(NamedTuple):
    """One day's timing rules (version 5: per-day start and evening drive)."""

    start: int  # minutes since midnight
    end: int
    evening_min: int  # longest first leg that may be driven the evening before; -1 = none


# A stop check: (node, leg, clock, day_end, max_wait) -> Attempt
TryFn = Callable[[dict, Leg, int, int, int], Attempt]


# ---------- Time helpers ----------

def to_minutes(t: time) -> int:
    return t.hour * 60 + t.minute


def to_time(minutes: int) -> time:
    return time(minutes // 60, minutes % 60)


def _hhmm(minutes: int) -> str:
    """HH:MM for messages. A rejected far-away stop can 'arrive' after midnight."""
    days, minutes = divmod(minutes, 24 * 60)
    text = f"{minutes // 60:02d}:{minutes % 60:02d}"
    return f"{text} (+{days} day)" if days else text


# ---------- One leg and one attempt ----------

def _leg(graph: nx.DiGraph, u: Hashable, v: Hashable, weights: Weights, cache: dict) -> Leg:
    """Travel along the lowest-weight path (same weights as TSP). Cached per schedule run."""
    if (u, v) not in cache:
        path = dijkstra(graph, u, v, weights).path
        edges = [graph.edges[a, b] for a, b in zip(path, path[1:])]
        cache[u, v] = Leg(
            duration_min=math.ceil(sum(e["duration_min"] for e in edges)),
            cost_lkr=round(sum(e["cost_lkr"] for e in edges), 2),
            mode=path_mode(edges),
        )
    return cache[u, v]


def path_mode(edges: Sequence[Mapping]) -> str | None:
    """Modes along a path, e.g. "bus" or "car+bus" (repeats merged); None when modes are off."""
    modes = [e["mode"] for e in edges if "mode" in e]
    merged = [m for i, m in enumerate(modes) if i == 0 or m != modes[i - 1]]
    return "+".join(merged) if merged else None


def _try_stop(node: dict, leg: Leg, clock: int, day_end: int, max_wait: int) -> Attempt:
    """Can this stop be visited if we leave now? Checks wait, closing time and day_end."""
    opening, closing = to_minutes(node["opening_time"]), to_minutes(node["closing_time"])
    arrival = clock + leg.duration_min
    visit_start = max(arrival, opening)
    wait = visit_start - arrival
    departure = visit_start + node["visit_duration_min"]

    if arrival >= closing:
        return Attempt(False, CLOSED, f"arrival {_hhmm(arrival)} is after closing {_hhmm(closing)}")
    if wait > max_wait:
        return Attempt(False, EARLY, f"opens {_hhmm(opening)}, arrival {_hhmm(arrival)} "
                                     f"needs {wait} min wait (limit {max_wait})")
    if departure > closing:
        return Attempt(False, CLOSED, f"visit would end {_hhmm(departure)}, "
                                      f"after closing {_hhmm(closing)}")
    if departure > day_end:
        return Attempt(False, DAY_END, f"visit would end {_hhmm(departure)}, "
                                       f"after day end {_hhmm(day_end)}")
    return Attempt(True, None, "", arrival, wait, departure, leg)


def _never_fits(node: dict, trip: TripRequest) -> str | None:
    """Reason if the visit is longer than the time the place is open inside the day window.

    With per-day start times, the earliest start of any day counts.
    """
    day_start = min(to_minutes(trip.start_of_day(d)) for d in range(1, trip.num_days + 1))
    start = max(to_minutes(node["opening_time"]), day_start)
    end = min(to_minutes(node["closing_time"]), to_minutes(trip.day_end))
    available = max(0, end - start)
    if node["visit_duration_min"] > available:
        return (f"visit takes {node['visit_duration_min']} min but it is open only {available} min "
                f"within the day {_hhmm(day_start)}-{_hhmm(to_minutes(trip.day_end))}")
    return None


# ---------- Day windows (version 5: per-day start, evening drive) ----------

def day_window(trip: TripRequest, day: int, prev_end: int | None) -> DayWindow:
    """Timing of day `day`. prev_end: when the previous day's activity ended (None on day 1).

    Defaults (no day_starts, no evening limit) give the old day: day_start..day_end, no
    evening drive. An evening drive into this day must end by the previous day_end + limit.
    """
    end, limit = to_minutes(trip.day_end), trip.evening_limit_min()
    evening = end + limit - prev_end if prev_end is not None and limit > 0 else -1
    return DayWindow(to_minutes(trip.start_of_day(day)), end, evening)


def activity_end(clock: int, late_lunch: tuple[int, int] | None) -> int:
    """When the day's activity ends: the last departure, or the end of a lunch after it."""
    return late_lunch[1] + config.LUNCH_DURATION_MIN if late_lunch else clock


# ---------- Lunch rule (version 5) ----------

def lunch_window() -> tuple[int, int] | None:
    """(earliest, latest) lunch START in minutes, or None when the lunch flag is off."""
    if not config.USE_LUNCH_BREAK:
        return None
    return to_minutes(config.LUNCH_WINDOW_START), to_minutes(config.LUNCH_WINDOW_END)


def attempt(node: dict, leg: Leg, clock: int, day_end: int, max_wait: int,
            lunch_taken: bool = False, try_fn: TryFn = _try_stop, evening_min: int = -1) -> Attempt:
    """Check the next stop under the lunch rule, with the evening drive as a fallback.

    try_fn checks one stop: _try_stop (opening hours) or the naive one (day length only).
    evening_min: for a day's first stop, the longest leg that may be driven the evening
    before (DayWindow.evening_min); -1 = not allowed. Defaults = the old single check.
    """
    result = _attempt_with_lunch(node, leg, clock, day_end, max_wait, lunch_taken, try_fn)
    if result.ok or leg.duration_min > evening_min:
        return result
    # Drove there last evening: the traveller is at the place when the day starts.
    evening = _attempt_with_lunch(node, leg._replace(duration_min=0), clock, day_end, max_wait,
                                  lunch_taken, try_fn)
    return evening._replace(leg=leg, evening=True) if evening.ok else result


def _attempt_with_lunch(node: dict, leg: Leg, clock: int, day_end: int, max_wait: int,
                        lunch_taken: bool, try_fn: TryFn) -> Attempt:
    """The lunch rule around one stop check. Lunch off or already taken: just try_fn."""
    window = lunch_window()
    if window is None or lunch_taken or clock > window[1]:
        return try_fn(node, leg, clock, day_end, max_wait)
    earliest, latest = window
    plain = None
    if clock < earliest:  # lunch can wait, unless this visit would run past the window
        plain = try_fn(node, leg, clock, day_end, max_wait)
        if plain.ok and plain.departure <= latest:
            return plain
    start = max(clock, earliest)  # lunch first: now, or as soon as the window opens
    if start - clock > max_wait:  # same limit as waiting for a place to open; retry later today
        return plain if not plain.ok else Attempt(
            False, EARLY, f"lunch first: window opens {_hhmm(earliest)}, {start - clock} min wait (limit {max_wait})")
    after = try_fn(node, leg, start + config.LUNCH_DURATION_MIN, day_end, max_wait)
    if after.ok:
        return after._replace(lunch=(clock, start))
    return plain if plain is not None and not plain.ok else after


def close_day(clock: int, has_stops: bool, lunch_taken: bool, day_end: int) -> tuple[int, int] | None:
    """Lunch after the day's last stop when that stop ended inside the window: (free from, start)."""
    window = lunch_window()
    if (window is None or lunch_taken or not has_stops or not window[0] <= clock <= window[1]
            or clock + config.LUNCH_DURATION_MIN > day_end):
        return None
    return clock, clock


def make_lunch(after_stop: int, lunch: tuple[int, int]) -> MealBreak:
    free, start = lunch
    return MealBreak(after_stop=after_stop, free_time=to_time(free), wait_min=start - free,
                     start_time=to_time(start), end_time=to_time(start + config.LUNCH_DURATION_MIN),
                     food_cost_lkr=config.LUNCH_COST_LKR)


# ---------- One day ----------

def _make_stop(stop_id: Hashable, node: dict, result: Attempt) -> Stop:
    return Stop(
        destination_id=stop_id,
        name=node["name"],
        arrival_time=to_time(result.arrival),
        wait_min=result.wait,
        departure_time=to_time(result.departure),
        travel_time_min=result.leg.duration_min,
        travel_cost_lkr=result.leg.cost_lkr,
        entry_cost_lkr=node["cost_lkr"],
        score=node["score"],
        travel_mode=result.leg.mode,
        evening_drive=result.evening,
    )


def living_costs(day: int, num_days: int) -> dict[str, float]:
    """Food, night and other costs of one day (config.USE_DAILY_COSTS); all 0 when off."""
    if not config.USE_DAILY_COSTS:
        return {"food_cost_lkr": 0.0, "accommodation_cost_lkr": 0.0, "other_cost_lkr": 0.0}
    food = config.FOOD_PER_DAY_LKR + (0.0 if config.USE_LUNCH_BREAK else config.LUNCH_COST_LKR)
    night = config.ACCOMMODATION_PER_NIGHT_LKR if day < num_days else 0.0  # no night after the last day
    return {"food_cost_lkr": food, "accommodation_cost_lkr": night, "other_cost_lkr": config.OTHER_PER_DAY_LKR}


def make_day_plan(day: int, stops: list[Stop], lunch: MealBreak | None, num_days: int) -> DayPlan:
    """A DayPlan and its cost: entry + travel of every stop, lunch, and living costs (version 5)."""
    living = living_costs(day, num_days)
    cost = sum(s.travel_cost_lkr + s.entry_cost_lkr for s in stops)
    if lunch is not None:
        cost += lunch.food_cost_lkr
    cost += sum(living.values())  # + 0.0 when the flag is off, which leaves the total unchanged
    return DayPlan(day=day, stops=stops, lunch=lunch, daily_cost_lkr=round(cost, 2), **living)


def _fill_day(day, queue, location, graph, trip, weights, max_wait, cache, reasons, window: DayWindow):
    """Place stops from the queue (in order) into one day.

    Returns (DayPlan, location, placed ids, end of the day's activity).
    """
    clock, day_end = window.start, window.end
    candidates = list(queue)  # not yet tried, or retryable (EARLY) today
    stops: list[Stop] = []
    placed: set = set()
    lunch: MealBreak | None = None

    progress = True
    while progress:
        progress = False
        for stop_id in list(candidates):
            node = graph.nodes[stop_id]
            result = attempt(node, _leg(graph, location, stop_id, weights, cache),
                             clock, day_end, max_wait, lunch is not None,
                             evening_min=-1 if stops else window.evening_min)
            if result.ok:
                if result.lunch:
                    lunch = make_lunch(len(stops), result.lunch)
                stops.append(_make_stop(stop_id, node, result))
                placed.add(stop_id)
                candidates.remove(stop_id)
                clock, location = result.departure, stop_id
                progress = True
                break  # restart the scan so skipped EARLY stops get another chance
            reasons[stop_id] = f"day {day}: {result.reason}"
            if result.kind != EARLY:
                candidates.remove(stop_id)  # deferred to the next day

    late_lunch = close_day(clock, bool(stops), lunch is not None, day_end)
    if late_lunch:
        lunch = make_lunch(len(stops), late_lunch)
    return make_day_plan(day, stops, lunch, trip.num_days), location, placed, activity_end(clock, late_lunch)


# ---------- Public API ----------

def schedule_days(
    order: Sequence[Hashable],
    graph: nx.DiGraph,
    trip_request: TripRequest,
    weights: Weights = config.EDGE_WEIGHTS,
    max_wait_min: int = config.MAX_WAIT_MIN,
) -> ScheduleResult:
    """Split the visit order (starting at START) into num_days DayPlans.

    Returns ScheduleResult(days, unscheduled). Every input stop ends up in exactly one of them.
    """
    if not order or order[0] != config.START_NODE_ID:
        raise ValueError(f"order must start with {config.START_NODE_ID!r}")
    for stop_id in order:
        if stop_id not in graph:
            raise KeyError(f"stop {stop_id!r} is not in the graph")

    reasons: dict[Hashable, str] = {}
    pending = []
    for stop_id in order[1:]:
        problem = _never_fits(graph.nodes[stop_id], trip_request)
        if problem:
            reasons[stop_id] = problem
        else:
            pending.append(stop_id)

    days, location, cache, prev_end = [], config.START_NODE_ID, {}, None
    for day in range(1, trip_request.num_days + 1):
        window = day_window(trip_request, day, prev_end)
        plan, location, placed, prev_end = _fill_day(day, pending, location, graph, trip_request,
                                                     weights, max_wait_min, cache, reasons, window)
        days.append(plan)
        pending = [s for s in pending if s not in placed]  # keeps TSP order for the next day

    scheduled = {s.destination_id for d in days for s in d.stops}
    unscheduled = [
        UnscheduledStop(destination_id=s, name=graph.nodes[s]["name"], reason=reasons[s])
        for s in order[1:] if s not in scheduled
    ]
    return ScheduleResult(days, unscheduled)


def schedule_fixed(
    day_orders: Sequence[Sequence[Hashable]],
    graph: nx.DiGraph,
    trip_request: TripRequest,
    weights: Weights = config.EDGE_WEIGHTS,
    max_wait_min: int = config.MAX_WAIT_MIN,
    cache: dict | None = None,
) -> list[DayPlan] | None:
    """Schedule exactly the given stops on the given days, in the given order.

    Unlike schedule_days nothing is skipped or deferred: returns None as soon as one
    stop does not fit (closed, too long a wait, or past day_end). Same timing rules,
    so the sequential plan's own day orders rebuild to the same times.
    Pass a cache dict to reuse travel legs across many calls (used by the joint optimizer).
    """
    if len(day_orders) != trip_request.num_days:
        raise ValueError(f"expected {trip_request.num_days} days, got {len(day_orders)}")
    cache = {} if cache is None else cache
    location, days, prev_end = config.START_NODE_ID, [], None

    for day, stop_ids in enumerate(day_orders, start=1):
        window = day_window(trip_request, day, prev_end)
        clock, stops, lunch = window.start, [], None
        for stop_id in stop_ids:
            node = graph.nodes[stop_id]
            result = attempt(node, _leg(graph, location, stop_id, weights, cache),
                             clock, window.end, max_wait_min, lunch is not None,
                             evening_min=-1 if stops else window.evening_min)
            if not result.ok:
                return None
            if result.lunch:
                lunch = make_lunch(len(stops), result.lunch)
            stops.append(_make_stop(stop_id, node, result))
            clock, location = result.departure, stop_id
        late_lunch = close_day(clock, bool(stops), lunch is not None, window.end)
        if late_lunch:
            lunch = make_lunch(len(stops), late_lunch)
        days.append(make_day_plan(day, stops, lunch, trip_request.num_days))
        prev_end = activity_end(clock, late_lunch)
    return days


def validate_opening_hours(day_plans: Sequence[DayPlan], graph: nx.DiGraph) -> list[str]:
    """Independent re-check of every scheduled stop. Returns conflicts (empty list = valid).

    Checks: the place exists, the visit starts at or after opening, lasts the full
    visit duration, and ends by closing.
    """
    return [c for plan in day_plans for stop in plan.stops for c in _stop_conflicts(plan.day, stop, graph)]


def count_conflicting_stops(day_plans: Sequence[DayPlan], graph: nx.DiGraph) -> int:
    """How many scheduled stops have at least one opening-hour conflict (used by the objective).

    Counted per stop, not per message: a visit that both starts too early and is too
    short is still one bad visit.
    """
    return sum(bool(_stop_conflicts(plan.day, stop, graph)) for plan in day_plans for stop in plan.stops)


def _stop_conflicts(day: int, stop: Stop, graph: nx.DiGraph) -> list[str]:
    """Conflict messages for one stop (empty list = the visit fits the opening hours)."""
    label = f"day {day}, {stop.destination_id}"
    if stop.destination_id not in graph:
        return [f"{label}: not in the graph"]
    node = graph.nodes[stop.destination_id]
    opening, closing = to_minutes(node["opening_time"]), to_minutes(node["closing_time"])
    visit_start = to_minutes(stop.arrival_time) + stop.wait_min
    departure = to_minutes(stop.departure_time)

    conflicts = []
    if visit_start < opening:
        conflicts.append(f"{label}: visit starts {_hhmm(int(visit_start))}, "
                         f"before opening {_hhmm(opening)}")
    if departure > closing:
        conflicts.append(f"{label}: leaves {_hhmm(departure)}, after closing {_hhmm(closing)}")
    if departure - visit_start < node["visit_duration_min"]:
        conflicts.append(f"{label}: visit is {departure - visit_start:g} min, "
                         f"needs {node['visit_duration_min']} min")
    return conflicts


def timeline(day: DayPlan) -> list[tuple[str, time, time]]:
    """The day in order, lunch included: (what, start, end). A visit's start is after any wait."""
    events = []
    for i, stop in enumerate(day.stops):
        if day.lunch is not None and day.lunch.after_stop == i:
            events.append(("lunch", day.lunch.start_time, day.lunch.end_time))
        start = to_time(to_minutes(stop.arrival_time) + int(stop.wait_min))
        events.append((stop.destination_id, start, stop.departure_time))
    if day.lunch is not None and day.lunch.after_stop == len(day.stops):
        events.append(("lunch", day.lunch.start_time, day.lunch.end_time))
    return events
