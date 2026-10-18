"""End-to-end pipelines that turn destinations + a trip request into an Itinerary.

run_sequential() is the SEQUENTIAL BASELINE: each step runs once, in order,
and nothing later can change an earlier decision.

    1. distance matrix (cache / Google / haversine)  -> 2. weighted graph
    3. TSP order on travel weight only (nearest neighbour + 2-opt)
    4. greedy day scheduling (opening hours checked here)
    5. budget allocation + overrun report (only reported, no feedback into the order)

The joint optimizer (to come) will be compared against this with the same
objective (src/objective.py) and metrics (src/metrics.py).
"""

from collections.abc import Sequence
from pathlib import Path
from typing import NamedTuple

import networkx as nx

from src import config
from src.budget import OverrunReport, allocate_budget, check_overruns
from src.distance import get_matrix_with_start
from src.graph import build_graph
from src.models import DayPlan, Destination, Itinerary, TripRequest
from src.objective import PlanScore, score_plan
from src.routing import shortest_path_matrix
from src.scheduler import schedule_days
from src.tsp import nearest_neighbor_order, two_opt


class PipelineResult(NamedTuple):
    itinerary: Itinerary
    score: PlanScore  # .total and .breakdown
    budget_report: OverrunReport
    graph: nx.DiGraph  # kept for evaluation (opening-hours check)


def apply_budget(day_plans: Sequence[DayPlan], report: OverrunReport) -> list[DayPlan]:
    """Copy each day with its allocated budget and overrun flag filled in."""
    by_day = {d.day: d for d in report.days}
    return [
        plan.model_copy(update={"daily_budget_lkr": by_day[plan.day].allocated_lkr,
                                "over_budget": by_day[plan.day].over_budget})
        for plan in day_plans
    ]


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

    allocation = allocate_budget(schedule.days, trip_request)
    report = check_overruns(schedule.days, allocation)

    itinerary = Itinerary(
        days=apply_budget(schedule.days, report),
        total_budget_lkr=trip_request.total_budget_lkr,
        total_cost_lkr=report.trip.total_planned_lkr,
        over_budget=report.trip.over_budget,
        unscheduled=schedule.unscheduled,
    )
    score = score_plan(itinerary.days, itinerary.unscheduled, report)
    return PipelineResult(itinerary, score, report, graph)
