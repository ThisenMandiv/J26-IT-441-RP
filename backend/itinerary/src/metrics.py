"""Evaluation metrics for one itinerary (see Evaluation in CLAUDE.md).

evaluate_plan() reports, for a single plan:
- total travel time (minutes)
- budget adherence: within budget or not, and by how much it is over
- opening-hour conflicts, found by scheduler.validate_opening_hours
- how many places were scheduled / left out

Travel-time reduction (%) compares two plans, so it is computed from two of these results.
"""

from collections.abc import Sequence
from typing import NamedTuple

import networkx as nx

from src.budget import OverrunReport
from src.models import DayPlan, UnscheduledStop
from src.scheduler import validate_opening_hours


class PlanMetrics(NamedTuple):
    travel_time_min: float
    within_budget: bool  # whole trip cost <= total budget (reserve may be used)
    overrun_lkr: float  # trip cost minus total budget, 0 when within budget
    conflicts: list[str]  # empty when every visit fits opening hours
    conflict_rate: float  # conflicts per scheduled place (0 when nothing scheduled)
    num_scheduled: int
    num_unscheduled: int


def evaluate_plan(
    day_plans: Sequence[DayPlan],
    unscheduled: Sequence[UnscheduledStop],
    budget_report: OverrunReport,
    graph: nx.DiGraph,
) -> PlanMetrics:
    """Metrics for one plan. The graph supplies opening hours for the conflict check."""
    num_scheduled = sum(len(d.stops) for d in day_plans)
    conflicts = validate_opening_hours(day_plans, graph)
    return PlanMetrics(
        travel_time_min=round(sum(s.travel_time_min for d in day_plans for s in d.stops), 2),
        within_budget=not budget_report.trip.over_budget,
        overrun_lkr=budget_report.trip.overrun_lkr,
        conflicts=conflicts,
        conflict_rate=len(conflicts) / num_scheduled if num_scheduled else 0.0,
        num_scheduled=num_scheduled,
        num_unscheduled=len(unscheduled),
    )
