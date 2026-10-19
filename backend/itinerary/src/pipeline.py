"""End-to-end pipelines that turn destinations + a trip request into an Itinerary.

run_sequential() is the SEQUENTIAL BASELINE: each step runs once, in order,
and nothing later can change an earlier decision.

    1. distance matrix (cache / Google / haversine)  -> 2. weighted graph
    3. TSP order on travel weight only (nearest neighbour + 2-opt)
    4. greedy day scheduling (opening hours checked here)
    5. budget allocation + overrun report (only reported, no feedback into the order)

run_naive() is the NAIVE BASELINE: it stands for route planners that do not look
at opening hours at all while routing.

    1. visit order by road distance only (nearest neighbour, no 2-opt)
    2. fill days in that order: a stop goes on today if the visit ends by day_end,
       otherwise it starts the next day. Opening hours are NOT checked, no waiting.
    3. budget is only reported (no feedback)
    4. validate_opening_hours then counts the conflicts this causes

All plans are scored with the same objective (src/objective.py) and metrics (src/metrics.py).
"""

import math
from collections.abc import Hashable, Mapping, Sequence
from pathlib import Path
from typing import NamedTuple

import networkx as nx

from src import config
from src.budget import OverrunReport, allocate_budget, check_overruns, cost_breakdown
from src.distance import get_matrix_with_start
from src.graph import build_graph
from src.models import DayPlan, Destination, Itinerary, TripRequest, UnscheduledStop
from src.objective import PlanScore, score_plan
from src.routing import shortest_path_matrix
from src.scheduler import (DAY_END, Attempt, Leg, ScheduleResult, _hhmm, _make_stop, activity_end, attempt,
                           close_day, day_window, make_day_plan, make_lunch, schedule_days,
                           validate_opening_hours)
from src.tsp import nearest_neighbor_order, two_opt


class PipelineResult(NamedTuple):
    itinerary: Itinerary
    score: PlanScore  # .total and .breakdown
    budget_report: OverrunReport
    graph: nx.DiGraph  # kept for evaluation (opening-hours check)


class NaiveResult(NamedTuple):
    itinerary: Itinerary
    score: PlanScore
    budget_report: OverrunReport
    graph: nx.DiGraph
    conflicts: list[str]  # from validate_opening_hours; usually NOT empty


def apply_budget(day_plans: Sequence[DayPlan], report: OverrunReport) -> list[DayPlan]:
    """Copy each day with its allocated budget and overrun flag filled in."""
    by_day = {d.day: d for d in report.days}
    return [
        plan.model_copy(update={"daily_budget_lkr": by_day[plan.day].allocated_lkr,
                                "over_budget": by_day[plan.day].over_budget})
        for plan in day_plans
    ]


def _finish(days: list[DayPlan], unscheduled: list[UnscheduledStop], trip_request: TripRequest,
            graph: nx.DiGraph):
    """Allocate the budget, check overruns, build the Itinerary and score it (incl. hour conflicts)."""
    report = check_overruns(days, allocate_budget(days, trip_request))
    itinerary = Itinerary(
        days=apply_budget(days, report),
        total_budget_lkr=trip_request.total_budget_lkr,
        total_cost_lkr=report.trip.total_planned_lkr,
        over_budget=report.trip.over_budget,
        unscheduled=unscheduled,
        cost_breakdown=cost_breakdown(days),
    )
    return itinerary, score_plan(itinerary.days, itinerary.unscheduled, report, graph=graph), report


def run_sequential(
    destinations: Sequence[Destination],
    trip_request: TripRequest,
    use_google: bool = False,
    cache_dir: str | Path = config.CACHE_DIR,
    mode_weights: Mapping[str, float] | None = None,
) -> PipelineResult:
    """Sequential baseline: route by travel weight first, then check hours, then budget.

    mode_weights: the traveller's objective weights, only used to pick a transport mode
    per leg when config.USE_TRANSPORT_MODES is on (see graph.build_graph).
    """
    matrix = get_matrix_with_start(destinations, trip_request,
                                   use_google=use_google, cache_dir=cache_dir)
    graph = build_graph(destinations, matrix, trip_request, mode_weights=mode_weights)

    # Travel weight only (time + cost of driving, config.EDGE_WEIGHTS): no hours, no budget.
    costs = shortest_path_matrix(graph, config.EDGE_WEIGHTS)
    order, _ = two_opt(nearest_neighbor_order(costs), costs)

    schedule = schedule_days(order, graph, trip_request, config.EDGE_WEIGHTS)

    itinerary, score, report = _finish(schedule.days, schedule.unscheduled, trip_request, graph)
    return PipelineResult(itinerary, score, report, graph)


# ---------- Naive baseline ----------

def distance_matrix(graph: nx.DiGraph) -> dict:
    """Direct road distance (km) between every pair, in the shape the TSP functions expect."""
    return {u: {v: {"weight": graph.edges[u, v]["distance_km"]} for v in graph.successors(u)}
            for u in graph.nodes}


def _try_ignoring_hours(node: dict, leg: Leg, clock: int, day_end: int, max_wait: int) -> Attempt:
    """Naive stop check: only the day length. The visit starts on arrival; hours are ignored."""
    arrival = clock + leg.duration_min
    departure = arrival + node["visit_duration_min"]
    if departure > day_end:
        return Attempt(False, DAY_END, f"visit would end {_hhmm(departure)}, after day end {_hhmm(day_end)}")
    return Attempt(True, None, "", arrival, 0, departure, leg)


def schedule_ignoring_hours(order: Sequence[Hashable], graph: nx.DiGraph,
                            trip_request: TripRequest) -> ScheduleResult:
    """Fill days in visit order, checking only the day length. Opening hours are ignored.

    The visit starts the moment the traveller arrives (no waiting). A stop that would end
    after day_end moves to the next day, where the traveller starts from where they slept.
    Stops still left after the last day are unscheduled.
    The version 5 traveller rules (lunch break, per-day start, evening drive) apply here
    too, through scheduler.day_window and scheduler.attempt.
    """
    queue, location = list(order[1:]), order[0]
    days: list[DayPlan] = []
    too_long: list[Hashable] = []  # do not fit even as the first stop of a fresh day
    prev_end = None
    for day in range(1, trip_request.num_days + 1):
        window = day_window(trip_request, day, prev_end)
        clock, day_end, stops, lunch = window.start, window.end, [], None
        while queue:
            stop_id, node = queue[0], graph.nodes[queue[0]]
            edge = graph.edges[location, stop_id]  # direct road, no shortest-path search
            leg = Leg(math.ceil(edge["duration_min"]), edge["cost_lkr"], edge.get("mode"))
            # max wait only limits idle time before lunch here: the naive check itself never waits
            result = attempt(node, leg, clock, day_end, config.MAX_WAIT_MIN, lunch is not None,
                             try_fn=_try_ignoring_hours, evening_min=-1 if stops else window.evening_min)
            if not result.ok and not stops:
                too_long.append(queue.pop(0))  # would block every later day
                continue
            if not result.ok:
                break  # try again tomorrow, keeping the order
            if result.lunch:
                lunch = make_lunch(len(stops), result.lunch)
            stops.append(_make_stop(stop_id, node, result))
            clock, location = result.departure, queue.pop(0)
        late_lunch = close_day(clock, bool(stops), lunch is not None, day_end)
        if late_lunch:
            lunch = make_lunch(len(stops), late_lunch)
        days.append(make_day_plan(day, stops, lunch, trip_request.num_days))
        prev_end = activity_end(clock, late_lunch)
    reasons = {**{s: "naive: drive + visit longer than the day" for s in too_long},
               **{s: "naive: did not fit in the trip's days" for s in queue}}
    unscheduled = [UnscheduledStop(destination_id=s, name=graph.nodes[s]["name"], reason=reason)
                   for s, reason in reasons.items()]
    return ScheduleResult(days, unscheduled)


def run_naive(
    destinations: Sequence[Destination],
    trip_request: TripRequest,
    use_google: bool = False,
    cache_dir: str | Path = config.CACHE_DIR,
    mode_weights: Mapping[str, float] | None = None,
) -> NaiveResult:
    """Naive baseline: nearest neighbour by distance, days filled in order, hours never checked.

    mode_weights: as in run_sequential (transport mode per leg, only when the flag is on).
    """
    matrix = get_matrix_with_start(destinations, trip_request,
                                   use_google=use_google, cache_dir=cache_dir)
    graph = build_graph(destinations, matrix, trip_request, mode_weights=mode_weights)
    order = nearest_neighbor_order(distance_matrix(graph))
    schedule = schedule_ignoring_hours(order, graph, trip_request)
    itinerary, score, report = _finish(schedule.days, schedule.unscheduled, trip_request, graph)
    return NaiveResult(itinerary, score, report, graph, validate_opening_hours(itinerary.days, graph))
