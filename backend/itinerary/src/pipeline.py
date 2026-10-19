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
from collections.abc import Hashable, Sequence
from pathlib import Path
from typing import NamedTuple

import networkx as nx

from src import config
from src.budget import OverrunReport, allocate_budget, check_overruns
from src.distance import get_matrix_with_start
from src.graph import build_graph
from src.models import DayPlan, Destination, Itinerary, Stop, TripRequest, UnscheduledStop
from src.objective import PlanScore, score_plan
from src.routing import shortest_path_matrix
from src.scheduler import ScheduleResult, schedule_days, to_minutes, to_time, validate_opening_hours
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


def _finish(days: list[DayPlan], unscheduled: list[UnscheduledStop], trip_request: TripRequest):
    """Allocate the budget, check overruns, build the Itinerary and score it."""
    report = check_overruns(days, allocate_budget(days, trip_request))
    itinerary = Itinerary(
        days=apply_budget(days, report),
        total_budget_lkr=trip_request.total_budget_lkr,
        total_cost_lkr=report.trip.total_planned_lkr,
        over_budget=report.trip.over_budget,
        unscheduled=unscheduled,
    )
    return itinerary, score_plan(itinerary.days, itinerary.unscheduled, report), report


def run_sequential(
    destinations: Sequence[Destination],
    trip_request: TripRequest,
    use_google: bool = False,
    cache_dir: str | Path = config.CACHE_DIR,
) -> PipelineResult:
    """Sequential baseline: route by travel weight first, then check hours, then budget."""
    matrix = get_matrix_with_start(destinations, trip_request,
                                   use_google=use_google, cache_dir=cache_dir)
    graph = build_graph(destinations, matrix, trip_request)

    # Travel weight only (time + cost of driving, config.EDGE_WEIGHTS): no hours, no budget.
    costs = shortest_path_matrix(graph, config.EDGE_WEIGHTS)
    order, _ = two_opt(nearest_neighbor_order(costs), costs)

    schedule = schedule_days(order, graph, trip_request, config.EDGE_WEIGHTS)

    itinerary, score, report = _finish(schedule.days, schedule.unscheduled, trip_request)
    return PipelineResult(itinerary, score, report, graph)


# ---------- Naive baseline ----------

def distance_matrix(graph: nx.DiGraph) -> dict:
    """Direct road distance (km) between every pair, in the shape the TSP functions expect."""
    return {u: {v: {"weight": graph.edges[u, v]["distance_km"]} for v in graph.successors(u)}
            for u in graph.nodes}


def schedule_ignoring_hours(order: Sequence[Hashable], graph: nx.DiGraph,
                            trip_request: TripRequest) -> ScheduleResult:
    """Fill days in visit order, checking only the day length. Opening hours are ignored.

    The visit starts the moment the traveller arrives (no waiting). A stop that would end
    after day_end moves to the next day, where the traveller starts from where they slept.
    Stops still left after the last day are unscheduled.
    """
    day_start, day_end = to_minutes(trip_request.day_start), to_minutes(trip_request.day_end)
    queue, location = list(order[1:]), order[0]
    days: list[DayPlan] = []
    too_long: list[Hashable] = []  # do not fit even as the first stop of a fresh day
    for day in range(1, trip_request.num_days + 1):
        clock, stops = day_start, []
        while queue:
            stop_id, node = queue[0], graph.nodes[queue[0]]
            edge = graph.edges[location, stop_id]
            arrival = clock + math.ceil(edge["duration_min"])
            departure = arrival + node["visit_duration_min"]
            if departure > day_end and not stops:
                too_long.append(queue.pop(0))  # would block every later day
                continue
            if departure > day_end:
                break  # try again tomorrow, keeping the order
            stops.append(Stop(destination_id=stop_id, name=node["name"], arrival_time=to_time(arrival),
                              departure_time=to_time(departure), travel_time_min=math.ceil(edge["duration_min"]),
                              travel_cost_lkr=edge["cost_lkr"], entry_cost_lkr=node["cost_lkr"],
                              score=node["score"]))
            clock, location = departure, queue.pop(0)
        cost = sum(s.travel_cost_lkr + s.entry_cost_lkr for s in stops)
        days.append(DayPlan(day=day, stops=stops, daily_cost_lkr=round(cost, 2)))
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
) -> NaiveResult:
    """Naive baseline: nearest neighbour by distance, days filled in order, hours never checked."""
    matrix = get_matrix_with_start(destinations, trip_request,
                                   use_google=use_google, cache_dir=cache_dir)
    graph = build_graph(destinations, matrix, trip_request)
    order = nearest_neighbor_order(distance_matrix(graph))
    schedule = schedule_ignoring_hours(order, graph, trip_request)
    itinerary, score, report = _finish(schedule.days, schedule.unscheduled, trip_request)
    return NaiveResult(itinerary, score, report, graph, validate_opening_hours(itinerary.days, graph))
