"""Joint constraint optimizer: hill climbing on the whole itinerary.

The sequential baseline decides the route first and only checks opening hours and
budget afterwards. Here every candidate is judged on ALL of them at once by the
single objective (src/objective.py): destination scores, travel time, spend,
waiting, unscheduled places and budget overruns.

    1. start from run_sequential's plan (so we can never end up worse)
    2. repeat max_iterations times:
         pick a random change: swap two stops / move a stop to another position or day /
                               drop a low-value stop / insert an unscheduled stop
         rebuild the days with scheduler.schedule_fixed (rejects if a stop does not fit)
         re-check opening hours, re-allocate the budget, score the plan
         keep the change only if the score is strictly higher
    3. return the best plan and a log of the accepted changes

A fixed seed makes the random choices, and so the result, repeatable.
"""

import random
from collections.abc import Hashable, Mapping, Sequence
from pathlib import Path
from typing import NamedTuple

import networkx as nx

from src import config
from src.budget import OverrunReport, allocate_budget, check_overruns
from src.models import DayPlan, Destination, Itinerary, TripRequest, UnscheduledStop
from src.objective import PlanScore, score_plan
from src.pipeline import PipelineResult, apply_budget, run_sequential
from src.scheduler import schedule_fixed, validate_opening_hours

DayOrders = list[list[Hashable]]  # stop ids per day, in visiting order
IMPROVEMENT_EPS = 1e-9
DROPPED_REASON = "dropped by joint optimizer: the plan scores higher without it"


class Move(NamedTuple):
    iteration: int
    description: str  # e.g. "drop D07 from day 1"
    score_after: float


class JointResult(NamedTuple):
    itinerary: Itinerary
    score: PlanScore
    budget_report: OverrunReport
    graph: nx.DiGraph
    moves: list[Move]  # accepted changes, in order
    baseline: PipelineResult  # the sequential plan we started from


class Candidate(NamedTuple):
    """A fully rebuilt and scored plan."""

    day_orders: DayOrders
    pool: list[Hashable]  # unscheduled ids
    days: list[DayPlan]
    unscheduled: list[UnscheduledStop]
    report: OverrunReport
    score: PlanScore


# ---------- Rebuild and score one candidate ----------

def _evaluate(day_orders, pool, reasons, graph, trip, weights, cache) -> Candidate | None:
    """Schedule, check hours, allocate budget and score. None if the plan is infeasible."""
    days = schedule_fixed(day_orders, graph, trip, cache=cache)
    if days is None or validate_opening_hours(days, graph):
        return None
    unscheduled = [UnscheduledStop(destination_id=s, name=graph.nodes[s]["name"], reason=reasons[s])
                   for s in pool]
    report = check_overruns(days, allocate_budget(days, trip))
    return Candidate(day_orders, pool, days, unscheduled, report,
                     score_plan(days, unscheduled, report, weights))


# ---------- Random changes (each returns new day orders, pool and a description) ----------

def _positions(day_orders: DayOrders) -> list[tuple[int, int]]:
    """(day index, position) of every scheduled stop."""
    return [(d, i) for d, stops in enumerate(day_orders) for i in range(len(stops))]


def _copy(day_orders: DayOrders) -> DayOrders:
    return [list(stops) for stops in day_orders]


def _random_slot(day_orders: DayOrders, rng: random.Random) -> tuple[int, int]:
    """A random (day index, insert position) anywhere in the plan, including empty days."""
    d = rng.randrange(len(day_orders))
    return d, rng.randint(0, len(day_orders[d]))


def _swap(day_orders, pool, rng, graph, weights):
    (d1, i1), (d2, i2) = rng.sample(_positions(day_orders), 2)
    new = _copy(day_orders)
    a, b = new[d1][i1], new[d2][i2]
    new[d1][i1], new[d2][i2] = b, a
    return new, pool, f"swap {a} (day {d1 + 1}) with {b} (day {d2 + 1})"


def _move(day_orders, pool, rng, graph, weights):
    d, i = rng.choice(_positions(day_orders))
    new = _copy(day_orders)
    stop = new[d].pop(i)
    nd, ni = _random_slot(new, rng)
    new[nd].insert(ni, stop)
    return new, pool, f"move {stop} from day {d + 1} to day {nd + 1}, position {ni + 1}"


def _stop_value(stop_id, graph, weights) -> float:
    """Rough worth of a stop on its own: score reward minus entry-fee penalty (travel ignored)."""
    node = graph.nodes[stop_id]
    return (weights["score"] * node["score"]
            - weights["spend"] * node["cost_lkr"] / config.OBJECTIVE_MONEY_SCALE_LKR)


def _drop(day_orders, pool, rng, graph, weights):
    ranked = sorted(_positions(day_orders),
                    key=lambda p: (_stop_value(day_orders[p[0]][p[1]], graph, weights),
                                   day_orders[p[0]][p[1]]))
    d, i = rng.choice(ranked[:config.JOINT_DROP_POOL])
    new = _copy(day_orders)
    stop = new[d].pop(i)
    return new, [*pool, stop], f"drop {stop} from day {d + 1}"


def _insert(day_orders, pool, rng, graph, weights):
    stop = rng.choice(pool)
    new = _copy(day_orders)
    d, i = _random_slot(new, rng)
    new[d].insert(i, stop)
    return new, [s for s in pool if s != stop], f"insert {stop} into day {d + 1}, position {i + 1}"


def _random_change(day_orders, pool, rng, graph, weights):
    """Pick one applicable kind of change at random and apply it to a copy."""
    scheduled = len(_positions(day_orders))
    kinds = []
    if scheduled >= 2:
        kinds.append(_swap)
    if scheduled >= 1:
        kinds += [_move, _drop]
    if pool:
        kinds.append(_insert)
    return rng.choice(kinds)(day_orders, pool, rng, graph, weights) if kinds else None


# ---------- Public API ----------

def optimize_joint(
    destinations: Sequence[Destination],
    trip_request: TripRequest,
    weights: Mapping[str, float] | None = None,
    max_iterations: int = config.JOINT_MAX_ITERATIONS,
    seed: int = config.JOINT_SEED,
    use_google: bool = False,
    cache_dir: str | Path = config.CACHE_DIR,
) -> JointResult:
    """Improve the sequential plan by hill climbing on the joint objective."""
    weights = config.OBJECTIVE_WEIGHTS if weights is None else weights
    baseline = run_sequential(destinations, trip_request, use_google, cache_dir)
    graph = baseline.graph
    rng = random.Random(seed)
    cache: dict = {}

    # Starting point: exactly the sequential plan, scored with *these* weights.
    start_orders = [[s.destination_id for s in d.stops] for d in baseline.itinerary.days]
    reasons = {u.destination_id: u.reason for u in baseline.itinerary.unscheduled}
    best = Candidate(start_orders, list(reasons), baseline.itinerary.days,
                     baseline.itinerary.unscheduled, baseline.budget_report,
                     score_plan(baseline.itinerary.days, baseline.itinerary.unscheduled,
                                baseline.budget_report, weights))
    moves: list[Move] = []

    for iteration in range(1, max_iterations + 1):
        change = _random_change(best.day_orders, best.pool, rng, graph, weights)
        if change is None:
            break  # nothing scheduled and nothing to insert
        day_orders, pool, description = change
        if description.startswith("drop"):
            reasons[pool[-1]] = DROPPED_REASON  # the dropped stop is appended to the pool
        candidate = _evaluate(day_orders, pool, reasons, graph, trip_request, weights, cache)
        if candidate and candidate.score.total > best.score.total + IMPROVEMENT_EPS:
            best = candidate
            moves.append(Move(iteration, description, candidate.score.total))

    itinerary = Itinerary(
        days=apply_budget(best.days, best.report),
        total_budget_lkr=trip_request.total_budget_lkr,
        total_cost_lkr=best.report.trip.total_planned_lkr,
        over_budget=best.report.trip.over_budget,
        unscheduled=best.unscheduled,  # sequential's order, then places dropped by joint
    )
    return JointResult(itinerary, best.score, best.report, graph, moves, baseline)
