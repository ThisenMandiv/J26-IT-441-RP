"""Tests for src/metrics.py: travel time, budget adherence and opening-hour conflicts."""

from datetime import time

import pytest

from src import config
from src.budget import allocate_budget, check_overruns
from src.distance import build_fake_matrix, start_location
from src.graph import build_graph
from src.loader import load_destinations
from src.metrics import (
    compare_joint_vs_sequential,
    evaluate_plan,
    format_comparison,
    travel_time_reduction_pct,
)
from src.models import DayPlan, Destination, Stop, TripRequest, UnscheduledStop

COLOMBO = (6.9344, 79.8428)


def setup(budget):
    """One invented place A, open 09:00-12:00, and a one-day trip."""
    t = TripRequest(num_days=1, total_budget_lkr=budget, start_lat=COLOMBO[0], start_lng=COLOMBO[1])
    a = Destination(id="A", name="Place A", lat=COLOMBO[0] + 0.02, lng=COLOMBO[1], category="test",
                    cost_lkr=1000, visit_duration_min=60, opening_time=time(9, 0),
                    closing_time=time(12, 0), score=0.5)
    return t, build_graph([a], build_fake_matrix([start_location(t), a]), t)


def plan(arrival, departure) -> list[DayPlan]:
    s = Stop(destination_id="A", name="Place A", arrival_time=arrival, departure_time=departure,
             travel_time_min=25, travel_cost_lkr=500, entry_cost_lkr=1000)
    return [DayPlan(day=1, stops=[s])]


def evaluate(days, budget, unscheduled=()):
    t, g = setup(budget)
    report = check_overruns(days, allocate_budget(days, t))
    return evaluate_plan(days, list(unscheduled), report, g)


def test_valid_plan_within_budget():
    left_out = UnscheduledStop(destination_id="B", name="Place B", reason="test")
    m = evaluate(plan(time(9, 0), time(10, 0)), budget=5_000, unscheduled=[left_out])
    assert m.travel_time_min == 25
    assert m.within_budget and m.overrun_lkr == 0
    assert m.conflicts == [] and m.conflict_rate == 0
    assert (m.num_scheduled, m.num_unscheduled) == (1, 1)


def test_over_budget_reports_amount():
    m = evaluate(plan(time(9, 0), time(10, 0)), budget=1_000)  # plan costs 1500
    assert not m.within_budget and m.overrun_lkr == 500


def test_opening_hour_conflict_is_counted():
    m = evaluate(plan(time(8, 0), time(9, 0)), budget=5_000)  # visit before 09:00 opening
    assert len(m.conflicts) == 1 and m.conflict_rate == 1.0


def test_empty_plan():
    m = evaluate([DayPlan(day=1)], budget=5_000)
    assert (m.travel_time_min, m.num_scheduled, m.conflict_rate) == (0, 0, 0.0)


# ---------- Joint vs sequential ----------

@pytest.mark.parametrize("baseline, new, expected", [(100, 80, 20.0), (100, 120, -20.0), (0, 0, 0.0)])
def test_travel_time_reduction_pct(baseline, new, expected):
    assert travel_time_reduction_pct(baseline, new) == expected


def test_compare_on_mock_data(tmp_path):
    t = TripRequest(num_days=3, total_budget_lkr=100_000, start_lat=COLOMBO[0], start_lng=COLOMBO[1])
    c = compare_joint_vs_sequential(load_destinations(config.DESTINATIONS_FILE), t,
                                    max_iterations=500, cache_dir=tmp_path)
    assert c.joint_score >= c.sequential_score
    for m in (c.sequential, c.joint):
        assert m.num_scheduled + m.num_unscheduled == 15
        assert m.conflicts == []
    assert c.travel_time_reduction_pct == travel_time_reduction_pct(
        c.sequential.travel_time_min, c.joint.travel_time_min)
    table = format_comparison(c)
    assert "objective score" in table and "travel time reduction" in table
