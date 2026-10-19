"""Objective function: one number for a complete itinerary (higher is better).

    total =  w_score       x sum of scores of scheduled places
           - w_travel_time x travel hours
           - w_spend       x planned spend   / 10,000 LKR
           - w_wait        x waiting hours (for places to open)
           - w_unscheduled x number of unscheduled places
           - w_overrun     x overrun amount  / 10,000 LKR
           - COVERAGE_PENALTY x places short of the coverage floor

Coverage floor: with n input places, the plan should visit at least
ceil(COVERAGE_FLOOR x n). Each place short of that costs COVERAGE_PENALTY. Without
it, a plan that visits nothing pays no travel, spend or overrun, and on tight budgets
it could outscore every real plan. The floor is the same under every weight setting.

Weights and scales come from src/config.py (OBJECTIVE_WEIGHTS), so they can be
tuned or learned later without touching this file. The same function scores the
sequential baseline, the naive baseline, the joint optimizer and the exact
benchmark, so they are compared fairly.
"""

import math
from collections.abc import Mapping, Sequence
from typing import NamedTuple

from src import config
from src.budget import OverrunReport, planned_cost
from src.models import DayPlan, UnscheduledStop

WEIGHT_KEYS = ("score", "travel_time", "spend", "wait", "unscheduled", "overrun")


def coverage_shortfall(num_scheduled: int, num_places: int, floor: float | None = None) -> int:
    """How many more places the plan needs to reach the coverage floor (0 if it does)."""
    floor = config.COVERAGE_FLOOR if floor is None else floor
    return max(0, math.ceil(floor * num_places - 1e-9) - num_scheduled)  # 1e-9: 0.3 x 10 is 3, not 3.0000001


class PlanScore(NamedTuple):
    total: float
    breakdown: dict  # raw totals, plus each weighted term under "terms"


def plan_totals(
    day_plans: Sequence[DayPlan],
    unscheduled: Sequence[UnscheduledStop],
    budget_report: OverrunReport,
) -> dict:
    """Raw (unweighted) totals of the plan, in their natural units."""
    stops = [s for d in day_plans for s in d.stops]
    return {
        "score_sum": round(sum(s.score for s in stops), 4),
        "travel_min": round(sum(s.travel_time_min for s in stops), 2),
        "spend_lkr": round(sum(planned_cost(d) for d in day_plans), 2),
        "wait_min": round(sum(s.wait_min for s in stops), 2),
        "unscheduled": len(unscheduled),
        "coverage_shortfall": coverage_shortfall(len(stops), len(stops) + len(unscheduled)),
        # Sum of per-day overruns, so a badly split budget is penalised even if the trip total fits.
        "overrun_lkr": round(sum(d.overrun_lkr for d in budget_report.days), 2),
    }


def score_plan(
    day_plans: Sequence[DayPlan],
    unscheduled: Sequence[UnscheduledStop],
    budget_report: OverrunReport,
    weights: Mapping[str, float] = config.OBJECTIVE_WEIGHTS,
) -> PlanScore:
    """Score a whole itinerary. Returns PlanScore(total, breakdown)."""
    missing = [k for k in WEIGHT_KEYS if k not in weights]
    if missing:
        raise KeyError(f"objective weights missing: {missing}")

    raw = plan_totals(day_plans, unscheduled, budget_report)
    hours, money = config.OBJECTIVE_TIME_SCALE_MIN, config.OBJECTIVE_MONEY_SCALE_LKR
    terms = {
        "score": weights["score"] * raw["score_sum"],
        "travel_time": -weights["travel_time"] * raw["travel_min"] / hours,
        "spend": -weights["spend"] * raw["spend_lkr"] / money,
        "wait": -weights["wait"] * raw["wait_min"] / hours,
        "unscheduled": -weights["unscheduled"] * raw["unscheduled"],
        "overrun": -weights["overrun"] * raw["overrun_lkr"] / money,
        "coverage": -config.COVERAGE_PENALTY * raw["coverage_shortfall"],
    }
    terms = {k: round(v, 4) for k, v in terms.items()}
    total = round(sum(terms.values()), 4)
    return PlanScore(total, {**raw, "terms": terms, "total": total})
