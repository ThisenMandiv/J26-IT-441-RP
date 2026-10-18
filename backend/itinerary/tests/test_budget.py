"""Tests for src/budget.py: allocation, overrun report and drop suggestions."""

import copy
from datetime import time

import pytest

from src import config
from src.budget import (
    allocate_budget,
    check_overruns,
    planned_cost,
    suggest_reductions,
)
from src.distance import build_fake_matrix, start_location
from src.graph import build_graph
from src.loader import load_destinations
from src.models import DayPlan, Destination, Stop, TripRequest
from src.routing import shortest_path_matrix
from src.scheduler import schedule_days
from src.tsp import nearest_neighbor_order, two_opt

START = config.START_NODE_ID
COLOMBO = (6.9344, 79.8428)


# ---------- Helpers ----------

def trip(num_days=2, budget=50_000.0) -> TripRequest:
    return TripRequest(num_days=num_days, total_budget_lkr=budget,
                       start_lat=COLOMBO[0], start_lng=COLOMBO[1])


def stop(id, entry, travel=0.0) -> Stop:
    return Stop(destination_id=id, name=f"Place {id}", arrival_time=time(9, 0),
                departure_time=time(10, 0), travel_time_min=10, travel_cost_lkr=travel,
                entry_cost_lkr=entry)


def day(n, *stops) -> DayPlan:
    return DayPlan(day=n, stops=list(stops))


def mock_days(num_days, budget):
    """Real pipeline on all 15 mock destinations: graph, TSP order, schedule."""
    dests = load_destinations(config.DESTINATIONS_FILE)
    t = trip(num_days, budget)
    g = build_graph(dests, build_fake_matrix([start_location(t), *dests]), t)
    costs = shortest_path_matrix(g)
    order, _ = two_opt(nearest_neighbor_order(costs), costs)
    return schedule_days(order, g, t).days, g, t


@pytest.fixture
def line_graph():
    """START + A, B, C on a line going north (invented values) for suggestion tests."""
    def dest(id, km, cost, score):
        return Destination(id=id, name=f"Place {id}", lat=COLOMBO[0] + km / 111, lng=COLOMBO[1],
                           category="test", cost_lkr=cost, visit_duration_min=60,
                           opening_time=time(6, 0), closing_time=time(20, 0), score=score)
    dests = [dest("A", 5, 3000, 0.9), dest("B", 10, 3000, 0.4), dest("C", 15, 500, 0.7)]
    t = trip(num_days=1, budget=5_000)
    return build_graph(dests, build_fake_matrix([start_location(t), *dests]), t), t


# ---------- planned_cost ----------

def test_planned_cost_is_entry_plus_travel():
    assert planned_cost(day(1, stop("A", 1000, 250), stop("B", 500, 100))) == 1850


# ---------- allocate_budget ----------

@pytest.mark.parametrize("method", ["proportional", "equal"])
@pytest.mark.parametrize("reserve", [0.0, 0.1, 0.25])
def test_allocations_sum_to_budget_minus_reserve(method, reserve):
    days = [day(1, stop("A", 1000)), day(2, stop("B", 2333.33)), day(3, stop("C", 1234.56))]
    alloc = allocate_budget(days, trip(3, 100_000), reserve_pct=reserve, method=method)
    assert alloc.reserve_lkr == pytest.approx(100_000 * reserve)
    assert sum(alloc.per_day.values()) == pytest.approx(100_000 - alloc.reserve_lkr, abs=1e-6)


def test_default_reserve_comes_from_config():
    alloc = allocate_budget([day(1, stop("A", 1000)), day(2)], trip(2, 10_000))
    assert alloc.reserve_lkr == pytest.approx(10_000 * config.BUDGET_RESERVE_PCT)
    assert alloc.method == config.BUDGET_SPLIT_METHOD


def test_proportional_split_follows_planned_cost():
    days = [day(1, stop("A", 1000)), day(2, stop("B", 3000))]
    alloc = allocate_budget(days, trip(2, 10_000), reserve_pct=0.2, method="proportional")
    assert alloc.per_day == {1: 2000.0, 2: 6000.0}  # 8000 spendable, split 1:3


def test_equal_split():
    days = [day(1, stop("A", 1000)), day(2, stop("B", 3000))]
    alloc = allocate_budget(days, trip(2, 10_000), reserve_pct=0.2, method="equal")
    assert alloc.per_day == {1: 4000.0, 2: 4000.0}


def test_allocation_is_rounded_to_cents():
    days = [day(n, stop("A", 1)) for n in (1, 2, 3)]
    alloc = allocate_budget(days, trip(3, 100.0), reserve_pct=0.0)
    assert all(round(v, 2) == v for v in alloc.per_day.values())
    assert sum(alloc.per_day.values()) == pytest.approx(100.0)


def test_invalid_inputs_rejected():
    days = [day(1), day(2)]
    with pytest.raises(ValueError, match="reserve_pct"):
        allocate_budget(days, trip(2), reserve_pct=1.0)
    with pytest.raises(ValueError, match="method"):
        allocate_budget(days, trip(2), method="random")
    with pytest.raises(ValueError, match="expected 3 day plans"):
        allocate_budget(days, trip(3))


# ---------- check_overruns ----------

def test_trip_under_budget_has_no_overruns():
    days, _, t = mock_days(7, budget=500_000)
    report = check_overruns(days, allocate_budget(days, t))
    assert not any(d.over_budget for d in report.days)
    assert all(d.overrun_lkr == 0 for d in report.days)
    assert not report.trip.over_budget and not report.trip.uses_reserve
    assert report.trip.overrun_lkr == 0


def test_over_budget_day_flagged_with_right_amount():
    days = [day(1, stop("A", 1000)), day(2, stop("B", 9000))]
    alloc = allocate_budget(days, trip(2, 10_000), reserve_pct=0.2, method="equal")  # 4000 each
    d1, d2 = check_overruns(days, alloc).days
    assert (d1.planned_cost_lkr, d1.allocated_lkr, d1.overrun_lkr, d1.over_budget) == (1000, 4000, 0, False)
    assert (d2.planned_cost_lkr, d2.allocated_lkr, d2.overrun_lkr, d2.over_budget) == (9000, 4000, 5000, True)


def test_proportional_overrun_hits_every_day_equally():
    """Each day gets the same fraction of its own cost, so overruns scale with cost."""
    days = [day(1, stop("A", 1000)), day(2, stop("B", 3000))]
    alloc = allocate_budget(days, trip(2, 2_000), reserve_pct=0.0, method="proportional")
    d1, d2 = check_overruns(days, alloc).days
    assert d1.over_budget and d2.over_budget
    assert (d1.overrun_lkr, d2.overrun_lkr) == (500, 1500)  # 4000 planned vs 2000 budget, 1:3


def test_trip_level_totals():
    days = [day(1, stop("A", 6000)), day(2, stop("B", 5000))]
    report = check_overruns(days, allocate_budget(days, trip(2, 10_000), reserve_pct=0.1))
    assert report.trip.total_planned_lkr == 11_000
    assert report.trip.total_budget_lkr == 10_000
    assert report.trip.spendable_lkr == 9_000
    assert report.trip.over_budget and report.trip.overrun_lkr == 1_000


def test_trip_that_eats_into_reserve():
    days = [day(1, stop("A", 9500))]
    report = check_overruns(days, allocate_budget(days, trip(1, 10_000), reserve_pct=0.1))
    assert report.trip.uses_reserve and not report.trip.over_budget


def test_tolerance_allows_small_overrun():
    days = [day(1, stop("A", 1050))]
    alloc = allocate_budget(days, trip(1, 1000), reserve_pct=0.0)
    assert check_overruns(days, alloc, tolerance=0.0).days[0].over_budget
    assert not check_overruns(days, alloc, tolerance=0.1).days[0].over_budget


# ---------- Zero-cost day and one-day trip ----------

def test_zero_cost_day_gets_nothing_and_no_overrun():
    days = [day(1, stop("A", 0)), day(2, stop("B", 4000))]  # free place, e.g. a beach
    alloc = allocate_budget(days, trip(2, 10_000), reserve_pct=0.0)
    assert alloc.per_day[1] == 0
    d1, _ = check_overruns(days, alloc).days
    assert (d1.planned_cost_lkr, d1.overrun_lkr, d1.over_budget) == (0, 0, False)


def test_whole_trip_free_falls_back_to_equal_split():
    days = [day(1), day(2, stop("A", 0))]
    alloc = allocate_budget(days, trip(2, 10_000), reserve_pct=0.0)
    assert alloc.per_day == {1: 5000.0, 2: 5000.0}
    assert not any(d.over_budget for d in check_overruns(days, alloc).days)


def test_one_day_trip():
    days, g, t = mock_days(1, budget=10_000)
    alloc = allocate_budget(days, t)
    assert alloc.per_day == {1: pytest.approx(10_000 * (1 - config.BUDGET_RESERVE_PCT))}
    report = check_overruns(days, alloc)
    assert len(report.days) == 1
    assert report.trip.total_planned_lkr == report.days[0].planned_cost_lkr


# ---------- suggest_reductions ----------

def test_suggestions_only_for_overrun_days():
    days, g, t = mock_days(7, budget=150_000)
    report = check_overruns(days, allocate_budget(days, t, method="equal"))
    suggestions = suggest_reductions(days, report, g)
    assert set(suggestions) == {d.day for d in report.days if d.over_budget}


def test_suggestions_ordered_by_saving_and_never_start():
    days, g, t = mock_days(7, budget=100_000)
    report = check_overruns(days, allocate_budget(days, t))
    suggestions = suggest_reductions(days, report, g)
    assert suggestions  # this budget is too small, so there is something to suggest
    for options in suggestions.values():
        savings = [s.saving_lkr for s in options]
        assert savings == sorted(savings, reverse=True)
        assert all(s.destination_id != START for s in options)
        assert all(s.action == "drop" for s in options)


def test_start_is_skipped_even_if_present_in_a_plan(line_graph):
    g, t = line_graph
    days = [day(1, stop(START, 0, 0), stop("A", 3000, 500))]
    report = check_overruns(days, allocate_budget(days, t, reserve_pct=0.9))
    assert [s.destination_id for s in suggest_reductions(days, report, g)[1]] == ["A"]


def test_suggestions_do_not_change_plans():
    days, g, t = mock_days(7, budget=100_000)
    before = copy.deepcopy(days)
    report = check_overruns(days, allocate_budget(days, t))
    suggest_reductions(days, report, g)
    assert days == before


def test_drop_saving_includes_rerouted_travel(line_graph):
    """Dropping a middle stop saves its fee + legs in and out, minus the new direct leg."""
    g, t = line_graph
    order = [START, "A", "B", "C"]
    days = schedule_days(order, g, t).days
    report = check_overruns(days, allocate_budget(days, t))
    by_id = {s.destination_id: s for s in suggest_reductions(days, report, g)[1]}
    a, b, c = days[0].stops
    expected_b = b.entry_cost_lkr + b.travel_cost_lkr + c.travel_cost_lkr - g.edges["A", "C"]["cost_lkr"]
    assert by_id["B"].saving_lkr == pytest.approx(expected_b, abs=0.01)
    assert by_id["C"].saving_lkr == pytest.approx(c.entry_cost_lkr + c.travel_cost_lkr)  # last stop


def test_equal_saving_drops_lower_score_first():
    """Free travel, same 3000 fee: savings tie, so the lower-scored B is listed first
    even though A comes first in the day."""
    import networkx as nx

    g = nx.DiGraph()
    for node, score in [(START, 0.0), ("A", 0.9), ("B", 0.4)]:
        g.add_node(node, lat=COLOMBO[0], lng=COLOMBO[1], score=score)
    for u in g.nodes:
        for v in g.nodes:
            if u != v:
                g.add_edge(u, v, distance_km=0.0, duration_min=1.0, cost_lkr=0.0)
    days = [day(1, stop("A", 3000), stop("B", 3000))]
    report = check_overruns(days, allocate_budget(days, trip(1, 1000), reserve_pct=0.0))
    options = suggest_reductions(days, report, g)[1]
    assert [s.saving_lkr for s in options] == [3000, 3000]
    assert [s.destination_id for s in options] == ["B", "A"]


def test_clears_overrun_flag(line_graph):
    g, t = line_graph
    days = [day(1, stop("A", 3000), stop("C", 500))]  # 3500 planned
    alloc = allocate_budget(days, t, reserve_pct=0.4)  # 3000 allocated -> 500 over
    options = suggest_reductions(days, check_overruns(days, alloc), g)[1]
    flags = {s.destination_id: s.clears_overrun for s in options}
    assert flags == {"A": True, "C": True}  # dropping C (saves 500) is just enough
    assert options[0].destination_id == "A"  # bigger saving first


def test_no_suggestions_when_within_budget(line_graph):
    g, t = line_graph
    days = [day(1, stop("A", 100))]
    report = check_overruns(days, allocate_budget(days, t))
    assert suggest_reductions(days, report, g) == {}
