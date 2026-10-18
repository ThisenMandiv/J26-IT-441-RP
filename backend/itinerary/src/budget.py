"""Day-wise budget allocation and overrun alerts (WBS 3.7).

1. allocate_budget:     keep a reserve, split the rest of the trip budget across days
2. check_overruns:      compare each day's planned cost with its allocation
3. suggest_reductions:  for overrun days, which stop to drop and how much it saves

Planned cost of a day = entry costs + travel costs of its stops (from the scheduler).
Nothing here changes the day plans; every function only reads them.

Note on the default proportional split: every day gets the same fraction of its
own cost, so either every day overruns or none does. The "equal" split makes
per-day overruns differ (expensive days overrun, cheap days have spare).
"""

from collections.abc import Hashable, Mapping, Sequence
from typing import NamedTuple

import networkx as nx

from src import config
from src.models import DayPlan, Stop, TripRequest
from src.routing import dijkstra

SPLIT_METHODS = ("proportional", "equal")


class Allocation(NamedTuple):
    per_day: dict[int, float]  # day number -> allocated LKR
    reserve_lkr: float
    total_budget_lkr: float
    method: str


class DayBudget(NamedTuple):
    day: int
    planned_cost_lkr: float
    allocated_lkr: float
    overrun_lkr: float  # 0 when within the allocation
    over_budget: bool


class TripBudget(NamedTuple):
    total_planned_lkr: float
    total_budget_lkr: float
    reserve_lkr: float
    spendable_lkr: float  # total budget minus reserve
    overrun_lkr: float  # planned minus total budget, 0 when within budget
    over_budget: bool  # planned cost exceeds the whole budget
    uses_reserve: bool  # planned cost only fits by spending the reserve


class OverrunReport(NamedTuple):
    days: list[DayBudget]
    trip: TripBudget


class Suggestion(NamedTuple):
    day: int
    action: str  # "drop"
    destination_id: str
    name: str
    saving_lkr: float
    score: float
    clears_overrun: bool  # this change alone brings the day within its allocation


# ---------- Helpers ----------

def planned_cost(day: DayPlan) -> float:
    """Entry plus travel cost of every stop in the day."""
    return round(sum(s.entry_cost_lkr + s.travel_cost_lkr for s in day.stops), 2)


def _split_to_cents(amount: float, shares: Sequence[float]) -> list[float]:
    """Split amount by shares, rounded to cents; the rounding remainder goes to the last day."""
    total = sum(shares)
    parts = [round(amount * s / total, 2) for s in shares]
    parts[-1] = round(parts[-1] + amount - sum(parts), 2)
    return parts


# ---------- 1. Allocation ----------

def allocate_budget(
    day_plans: Sequence[DayPlan],
    trip_request: TripRequest,
    reserve_pct: float = config.BUDGET_RESERVE_PCT,
    method: str = config.BUDGET_SPLIT_METHOD,
) -> Allocation:
    """Keep reserve_pct of the budget back, split the rest across the days.

    proportional: each day gets a share matching its planned cost
                  (falls back to equal when the whole trip costs nothing)
    equal:        every day gets the same amount
    """
    if not 0 <= reserve_pct < 1:
        raise ValueError("reserve_pct must be in [0, 1)")
    if method not in SPLIT_METHODS:
        raise ValueError(f"method must be one of {SPLIT_METHODS}")
    if len(day_plans) != trip_request.num_days:
        raise ValueError(f"expected {trip_request.num_days} day plans, got {len(day_plans)}")

    total = trip_request.total_budget_lkr
    reserve = round(total * reserve_pct, 2)
    spendable = round(total - reserve, 2)

    costs = [planned_cost(d) for d in day_plans]
    shares = costs if method == "proportional" and sum(costs) > 0 else [1.0] * len(day_plans)
    amounts = _split_to_cents(spendable, shares)
    per_day = {d.day: amount for d, amount in zip(day_plans, amounts)}
    return Allocation(per_day, reserve, total, method)


# ---------- 2. Overruns ----------

def check_overruns(
    day_plans: Sequence[DayPlan],
    allocation: Allocation,
    tolerance: float = config.BUDGET_OVERRUN_TOLERANCE,
) -> OverrunReport:
    """Per day: planned, allocated, overrun, flag. Plus the trip-level totals.

    A day is flagged when it is more than `tolerance` (a fraction) over its allocation.
    """
    days = []
    for plan in day_plans:
        cost = planned_cost(plan)
        allocated = allocation.per_day[plan.day]
        overrun = round(max(0.0, cost - allocated), 2)
        days.append(DayBudget(plan.day, cost, allocated, overrun, overrun > allocated * tolerance))

    total_planned = round(sum(d.planned_cost_lkr for d in days), 2)
    spendable = round(allocation.total_budget_lkr - allocation.reserve_lkr, 2)
    trip = TripBudget(
        total_planned_lkr=total_planned,
        total_budget_lkr=allocation.total_budget_lkr,
        reserve_lkr=allocation.reserve_lkr,
        spendable_lkr=spendable,
        overrun_lkr=round(max(0.0, total_planned - allocation.total_budget_lkr), 2),
        over_budget=total_planned > allocation.total_budget_lkr,
        uses_reserve=spendable < total_planned <= allocation.total_budget_lkr,
    )
    return OverrunReport(days, trip)


# ---------- 3. Suggestions ----------

def _travel_cost(graph: nx.DiGraph, u: Hashable, v: Hashable, weights: Mapping) -> float:
    """Travel cost along the same lowest-weight path the scheduler uses."""
    path = dijkstra(graph, u, v, weights).path
    return sum(graph.edges[a, b]["cost_lkr"] for a, b in zip(path, path[1:]))


def _day_starts(day_plans: Sequence[DayPlan]) -> dict[int, Hashable]:
    """Where each day begins: START, then the last stop of the latest non-empty day."""
    starts, location = {}, config.START_NODE_ID
    for plan in day_plans:
        starts[plan.day] = location
        if plan.stops:
            location = plan.stops[-1].destination_id
    return starts


def _drop_saving(stops: list[Stop], i: int, start: Hashable, graph, weights) -> float:
    """Saving from dropping stop i: its entry fee + the legs into and out of it,
    minus the new direct leg from the previous place to the next stop."""
    stop = stops[i]
    saving = stop.entry_cost_lkr + stop.travel_cost_lkr
    if i + 1 < len(stops):
        prev = stops[i - 1].destination_id if i > 0 else start
        nxt = stops[i + 1]
        saving += nxt.travel_cost_lkr - _travel_cost(graph, prev, nxt.destination_id, weights)
    return round(saving, 2)


def suggest_reductions(
    day_plans: Sequence[DayPlan],
    overrun_report: OverrunReport,
    graph: nx.DiGraph,
    weights: Mapping[str, float] = config.EDGE_WEIGHTS,
) -> dict[int, list[Suggestion]]:
    """For each overrun day, every stop that could be dropped, biggest saving first.

    Ties go to the lower-scored stop (lose the least-wanted place). Only suggests:
    the day plans are not modified. The graph gives scores and the new travel leg.
    Limitation: dropping a day's last stop also moves where the next day starts;
    that knock-on change to the next day is not counted.
    """
    overrun = {d.day: d.overrun_lkr for d in overrun_report.days if d.over_budget}
    starts = _day_starts(day_plans)
    suggestions: dict[int, list[Suggestion]] = {}

    for plan in day_plans:
        if plan.day not in overrun:
            continue
        options = []
        for i, stop in enumerate(plan.stops):
            if stop.destination_id == config.START_NODE_ID:
                continue  # the start point is never a droppable visit
            saving = _drop_saving(plan.stops, i, starts[plan.day], graph, weights)
            score = graph.nodes[stop.destination_id]["score"]
            options.append(Suggestion(plan.day, "drop", stop.destination_id, stop.name,
                                      saving, score, saving >= overrun[plan.day]))
        options.sort(key=lambda s: (-s.saving_lkr, s.score))
        suggestions[plan.day] = options
    return suggestions
