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
"""

import math
from collections.abc import Hashable, Mapping, Sequence
from datetime import time
from typing import NamedTuple

import networkx as nx

from src import config
from src.models import DayPlan, Stop, TripRequest, UnscheduledStop
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


class Attempt(NamedTuple):
    ok: bool
    kind: str | None  # None when ok, else EARLY / CLOSED / DAY_END
    reason: str
    arrival: int = 0
    wait: int = 0
    departure: int = 0
    leg: Leg | None = None


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
        )
    return cache[u, v]


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
    """Reason if the visit is longer than the time the place is open inside the day window."""
    start = max(to_minutes(node["opening_time"]), to_minutes(trip.day_start))
    end = min(to_minutes(node["closing_time"]), to_minutes(trip.day_end))
    available = max(0, end - start)
    if node["visit_duration_min"] > available:
        return (f"visit takes {node['visit_duration_min']} min but it is open only {available} min "
                f"within the day {_hhmm(to_minutes(trip.day_start))}-{_hhmm(to_minutes(trip.day_end))}")
    return None


# ---------- One day ----------

def _make_stop(stop_id: Hashable, node: dict, attempt: Attempt) -> Stop:
    return Stop(
        destination_id=stop_id,
        name=node["name"],
        arrival_time=to_time(attempt.arrival),
        wait_min=attempt.wait,
        departure_time=to_time(attempt.departure),
        travel_time_min=attempt.leg.duration_min,
        travel_cost_lkr=attempt.leg.cost_lkr,
        entry_cost_lkr=node["cost_lkr"],
        score=node["score"],
    )


def _fill_day(day, queue, location, graph, trip, weights, max_wait, cache, reasons):
    """Place stops from the queue (in order) into one day. Returns (DayPlan, location, placed ids)."""
    clock, day_end = to_minutes(trip.day_start), to_minutes(trip.day_end)
    candidates = list(queue)  # not yet tried, or retryable (EARLY) today
    stops: list[Stop] = []
    placed: set = set()

    progress = True
    while progress:
        progress = False
        for stop_id in list(candidates):
            node = graph.nodes[stop_id]
            attempt = _try_stop(node, _leg(graph, location, stop_id, weights, cache),
                                clock, day_end, max_wait)
            if attempt.ok:
                stops.append(_make_stop(stop_id, node, attempt))
                placed.add(stop_id)
                candidates.remove(stop_id)
                clock, location = attempt.departure, stop_id
                progress = True
                break  # restart the scan so skipped EARLY stops get another chance
            reasons[stop_id] = f"day {day}: {attempt.reason}"
            if attempt.kind != EARLY:
                candidates.remove(stop_id)  # deferred to the next day

    cost = sum(s.travel_cost_lkr + s.entry_cost_lkr for s in stops)
    return DayPlan(day=day, stops=stops, daily_cost_lkr=round(cost, 2)), location, placed


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

    days, location, cache = [], config.START_NODE_ID, {}
    for day in range(1, trip_request.num_days + 1):
        plan, location, placed = _fill_day(day, pending, location, graph, trip_request,
                                           weights, max_wait_min, cache, reasons)
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
    day_start, day_end = to_minutes(trip_request.day_start), to_minutes(trip_request.day_end)
    location, days = config.START_NODE_ID, []

    for day, stop_ids in enumerate(day_orders, start=1):
        clock, stops = day_start, []
        for stop_id in stop_ids:
            node = graph.nodes[stop_id]
            attempt = _try_stop(node, _leg(graph, location, stop_id, weights, cache),
                                clock, day_end, max_wait_min)
            if not attempt.ok:
                return None
            stops.append(_make_stop(stop_id, node, attempt))
            clock, location = attempt.departure, stop_id
        cost = sum(s.travel_cost_lkr + s.entry_cost_lkr for s in stops)
        days.append(DayPlan(day=day, stops=stops, daily_cost_lkr=round(cost, 2)))
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
