"""Exact benchmark: the best possible plan under the objective, for small trips only.

Used in evaluation to measure how far the sequential baseline and the joint optimizer
are from the true optimum of the SAME objective (src/objective.py).

It searches every feasible plan: any subset of places, in any order, split over the
days, with the same timing rules as scheduler.schedule_fixed (opening hours, waiting
limit, day end). Depth-first search, one decision at a time:

    from the current state (day, location, clock, places visited):
      - visit one more unvisited place today, if it fits    -> new state, score it
      - or end today and continue tomorrow from here (only if today has a stop;
        an empty day in the middle gives the same plan as an empty day at the end,
        UNLESS days differ: with per-day start times or evening drives (version 5)
        an empty day can matter, so then empty middle days are searched too)

Every state is a complete plan (the remaining days stay empty), so each one is a
candidate. Branch and bound keeps this fast: adding stops can only ADD travel, spend,
waiting and overrun, so an optimistic bound for everything below a state is
    its score ignoring overrun + the best each remaining place could still add.
If that bound is not above the best plan found so far, the whole branch is skipped.
The search starts from the sequential plan as the best known plan.
"""

from collections.abc import Hashable, Mapping, Sequence
from pathlib import Path
from typing import NamedTuple

import networkx as nx

from src import config
from src.budget import OverrunReport, allocate_budget, check_overruns, cost_breakdown
from src.models import Destination, Itinerary, TripRequest, UnscheduledStop
from src.objective import PlanScore, coverage_shortfall, score_plan
from src.pipeline import apply_budget, run_sequential
from src.scheduler import (_leg, _never_fits, activity_end, attempt, close_day, day_window,  # same timing rules
                           schedule_fixed)

EPS = 1e-9
BOUND_TOL = 0.01  # plan_totals rounds to 2 decimals; never prune a branch over rounding noise
EXACT_REASON = "left out by the exact benchmark: the best plan does not include it"


class ExactResult(NamedTuple):
    itinerary: Itinerary
    score: PlanScore
    budget_report: OverrunReport
    graph: nx.DiGraph
    states_explored: int  # partial plans looked at (shows how much the bound pruned)


class _Totals(NamedTuple):
    """Running totals of a partial plan, for the quick bound."""

    score: float = 0.0
    travel_min: float = 0.0
    spend_lkr: float = 0.0
    wait_min: float = 0.0
    count: int = 0


class _Search:
    def __init__(self, graph, trip, weights, num_places):
        self.graph, self.trip, self.weights, self.n = graph, trip, weights, num_places
        self.cache: dict = {}
        # days can differ only with per-day starts or evening drives; then empty days may matter
        self.empty_days_matter = trip.day_starts is not None or trip.evening_limit_min() > 0
        self.best_score, self.best_orders = -float("inf"), None
        self.states = 0

    # ----- scoring -----

    def _quick(self, t: _Totals) -> float:
        """Objective of a partial plan WITHOUT the overrun term (so never below the true score)."""
        w, hours, money = self.weights, config.OBJECTIVE_TIME_SCALE_MIN, config.OBJECTIVE_MONEY_SCALE_LKR
        return (w["score"] * t.score - w["travel_time"] * t.travel_min / hours
                - w["spend"] * t.spend_lkr / money - w["wait"] * t.wait_min / hours
                - w["unscheduled"] * (self.n - t.count)
                - config.COVERAGE_PENALTY * coverage_shortfall(t.count, self.n))

    def _gain(self, place: Hashable) -> float:
        """Most one more place could add: its score reward and one fewer unscheduled, minus its fee."""
        node, w = self.graph.nodes[place], self.weights
        return (w["score"] * node["score"] + w["unscheduled"]
                - w["spend"] * node["cost_lkr"] / config.OBJECTIVE_MONEY_SCALE_LKR)

    def _bound(self, t: _Totals, remaining: list[Hashable]) -> float:
        coverage = config.COVERAGE_PENALTY * (coverage_shortfall(t.count, self.n)
                                              - coverage_shortfall(t.count + len(remaining), self.n))
        return self._quick(t) + sum(max(0.0, self._gain(p)) for p in remaining) + coverage

    def score_orders(self, day_orders):
        """True objective, built exactly as the other methods build their plans.
        Returns (PlanScore, days, unscheduled, OverrunReport), or None if infeasible."""
        days = schedule_fixed(day_orders, self.graph, self.trip, cache=self.cache)
        if days is None:
            return None
        unscheduled = _unscheduled(self.graph, day_orders)
        report = check_overruns(days, allocate_budget(days, self.trip))
        return score_plan(days, unscheduled, report, self.weights, self.graph), days, unscheduled, report

    def _hopeless(self, optimistic: float) -> bool:
        return optimistic + BOUND_TOL <= self.best_score + EPS

    def consider(self, day_orders, totals: _Totals):
        if self._hopeless(self._quick(totals)):
            return  # even with zero overrun it cannot win
        scored = self.score_orders(day_orders)
        if scored and scored[0].total > self.best_score + EPS:
            self.best_score, self.best_orders = scored[0].total, [list(d) for d in day_orders]

    # ----- depth-first search -----

    def run(self, candidates: list[Hashable]):
        orders = [[] for _ in range(self.trip.num_days)]
        self.consider(orders, _Totals())
        window = day_window(self.trip, 1, None)
        self._expand(0, config.START_NODE_ID, window.start, orders, candidates, _Totals(), window)

    def _expand(self, day, location, clock, orders, remaining, totals, window, lunch_taken=False):
        """day is 0-based; window = scheduler.day_window of this day (same rules as schedule_fixed).
        lunch_taken: today's lunch is already in the plan (only with config.USE_LUNCH_BREAK).
        Lunch costs and idle time are left out of _Totals, so the bound stays optimistic."""
        self.states += 1
        if self._hopeless(self._bound(totals, remaining)):
            return
        for place in remaining:
            node = self.graph.nodes[place]
            leg = _leg(self.graph, location, place, config.EDGE_WEIGHTS, self.cache)
            result = attempt(node, leg, clock, window.end, config.MAX_WAIT_MIN, lunch_taken,
                             evening_min=-1 if orders[day] else window.evening_min)
            if not result.ok:
                continue
            orders[day].append(place)
            new = _Totals(totals.score + node["score"], totals.travel_min + leg.duration_min,
                          totals.spend_lkr + leg.cost_lkr + node["cost_lkr"],
                          totals.wait_min + result.wait, totals.count + 1)
            rest = [p for p in remaining if p != place]
            self.consider(orders, new)
            self._expand(day, place, result.departure, orders, rest, new, window,
                         lunch_taken or result.lunch is not None)
            orders[day].pop()
        if (orders[day] or self.empty_days_matter) and day + 1 < self.trip.num_days:
            late_lunch = close_day(clock, bool(orders[day]), lunch_taken, window.end)
            tomorrow = day_window(self.trip, day + 2, activity_end(clock, late_lunch))
            self._expand(day + 1, location, tomorrow.start, orders, remaining, totals, tomorrow)


def exact_benchmark(
    destinations: Sequence[Destination],
    trip_request: TripRequest,
    weights: Mapping[str, float] | None = None,
    use_google: bool = False,
    cache_dir: str | Path = config.CACHE_DIR,
    max_places: int = config.EXACT_MAX_PLACES,
) -> ExactResult:
    """Best plan under the objective, by exhaustive search with pruning. Small trips only."""
    if len(destinations) > max_places:
        raise ValueError(f"exact benchmark allows at most {max_places} places, got {len(destinations)}")
    weights = config.OBJECTIVE_WEIGHTS if weights is None else weights
    # same graph as the others (with transport modes on: modes picked for these weights)
    baseline = run_sequential(destinations, trip_request, use_google, cache_dir, mode_weights=weights)
    graph = baseline.graph

    search = _Search(graph, trip_request, weights, len(destinations))
    seq_orders = [[s.destination_id for s in d.stops] for d in baseline.itinerary.days]
    search.best_score, search.best_orders = search.score_orders(seq_orders)[0].total, seq_orders
    # Places that can never fit in a day are skipped up front (they are unscheduled in every plan).
    candidates = [d.id for d in destinations if not _never_fits(graph.nodes[d.id], trip_request)]
    search.run(candidates)

    score, days, unscheduled, report = search.score_orders(search.best_orders)
    itinerary = Itinerary(
        days=apply_budget(days, report),
        total_budget_lkr=trip_request.total_budget_lkr,
        total_cost_lkr=report.trip.total_planned_lkr,
        over_budget=report.trip.over_budget,
        unscheduled=unscheduled,
        cost_breakdown=cost_breakdown(days),
    )
    return ExactResult(itinerary, score, report, graph, search.states)


def _unscheduled(graph: nx.DiGraph, day_orders) -> list[UnscheduledStop]:
    """Places not in the plan, with the exact benchmark's reason."""
    scheduled = {s for day in day_orders for s in day}
    return [UnscheduledStop(destination_id=p, name=graph.nodes[p]["name"], reason=EXACT_REASON)
            for p in graph.nodes if p != config.START_NODE_ID and p not in scheduled]
