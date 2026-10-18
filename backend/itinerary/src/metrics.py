"""Evaluation metrics for one itinerary (see Evaluation in CLAUDE.md).

evaluate_plan() reports, for a single plan:
- total travel time (minutes)
- budget adherence: within budget or not, and by how much it is over
- opening-hour conflicts, found by scheduler.validate_opening_hours
- how many places were scheduled / left out

compare_joint_vs_sequential() runs both approaches on the same input and adds the
travel-time reduction (%) of the joint plan against the sequential baseline.
"""

from collections.abc import Sequence
from typing import NamedTuple

import networkx as nx

from src.budget import OverrunReport
from src.joint import optimize_joint
from src.models import DayPlan, Destination, TripRequest, UnscheduledStop
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


# ---------- Joint vs sequential ----------

class Comparison(NamedTuple):
    sequential: PlanMetrics
    joint: PlanMetrics
    sequential_score: float
    joint_score: float
    travel_time_reduction_pct: float  # positive = joint drives less


def _metrics(result) -> PlanMetrics:
    """PlanMetrics for a PipelineResult or JointResult."""
    it = result.itinerary
    return evaluate_plan(it.days, it.unscheduled, result.budget_report, result.graph)


def travel_time_reduction_pct(baseline_min: float, new_min: float) -> float:
    """How much less travel the new plan needs, as % of the baseline (negative = more)."""
    return round((baseline_min - new_min) / baseline_min * 100, 2) if baseline_min else 0.0


def compare_joint_vs_sequential(
    destinations: Sequence[Destination],
    trip_request: TripRequest,
    **joint_kwargs,
) -> Comparison:
    """Run both approaches on the same input and put their metrics side by side.

    The sequential plan is the one the joint optimizer started from, so both use
    the same matrix and graph. joint_kwargs go to optimize_joint (seed, max_iterations, ...).
    Both scores use the default objective weights from config.
    """

    joint = optimize_joint(destinations, trip_request, **joint_kwargs)
    seq, jnt = _metrics(joint.baseline), _metrics(joint)
    return Comparison(
        sequential=seq,
        joint=jnt,
        sequential_score=joint.baseline.score.total,
        joint_score=joint.score.total,
        travel_time_reduction_pct=travel_time_reduction_pct(seq.travel_time_min, jnt.travel_time_min),
    )


def format_comparison(c: Comparison) -> str:
    """Plain-text table of a Comparison, for printing."""
    def row(label, seq, jnt):
        return f"{label:<28}{seq!s:>14}{jnt!s:>14}"

    s, j = c.sequential, c.joint
    lines = [
        row("metric", "sequential", "joint"),
        "-" * 56,
        row("objective score", c.sequential_score, c.joint_score),
        row("places scheduled", s.num_scheduled, j.num_scheduled),
        row("places unscheduled", s.num_unscheduled, j.num_unscheduled),
        row("total travel time (min)", s.travel_time_min, j.travel_time_min),
        row("within budget", s.within_budget, j.within_budget),
        row("budget overrun (LKR)", s.overrun_lkr, j.overrun_lkr),
        row("opening-hour conflicts", len(s.conflicts), len(j.conflicts)),
        row("conflict rate", s.conflict_rate, j.conflict_rate),
        "-" * 56,
        f"travel time reduction: {c.travel_time_reduction_pct:+.2f}%",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    from src import config
    from src.loader import load_destinations

    trip = TripRequest(num_days=3, total_budget_lkr=100_000, start_lat=6.9344, start_lng=79.8428)
    print("15 mock destinations, 3 days, 100,000 LKR, start Colombo (APPROX haversine matrix)")
    print(format_comparison(compare_joint_vs_sequential(load_destinations(config.DESTINATIONS_FILE), trip)))
