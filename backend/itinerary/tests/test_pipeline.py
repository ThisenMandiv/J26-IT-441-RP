"""Tests for src/pipeline.py: the sequential baseline on the 15-place mock data."""

import pytest

from src import config
from src.loader import load_destinations
from src.metrics import evaluate_plan
from src.models import Itinerary, TripRequest
from src.objective import score_plan
from src.pipeline import run_sequential
from src.scheduler import validate_opening_hours

COLOMBO = (6.9344, 79.8428)


def trip(num_days=3, budget=100_000.0) -> TripRequest:
    return TripRequest(num_days=num_days, total_budget_lkr=budget,
                       start_lat=COLOMBO[0], start_lng=COLOMBO[1])


@pytest.fixture
def destinations():
    dests = load_destinations(config.DESTINATIONS_FILE)
    assert len(dests) == 15
    return dests


@pytest.fixture
def run(destinations, tmp_path):
    """Run the baseline with the offline matrix, cached in a temp folder."""
    def _run(num_days=3, budget=100_000.0):
        return run_sequential(destinations, trip(num_days, budget), cache_dir=tmp_path)
    return _run


@pytest.mark.parametrize("num_days", [1, 3, 7])
def test_returns_valid_itinerary_without_conflicts(run, num_days):
    result = run(num_days)
    assert isinstance(result.itinerary, Itinerary)
    assert [d.day for d in result.itinerary.days] == list(range(1, num_days + 1))
    assert validate_opening_hours(result.itinerary.days, result.graph) == []


@pytest.mark.parametrize("num_days", [1, 3, 7])
def test_every_place_scheduled_or_unscheduled(run, destinations, num_days):
    it = run(num_days).itinerary
    scheduled = [s.destination_id for d in it.days for s in d.stops]
    unscheduled = [u.destination_id for u in it.unscheduled]
    assert sorted(scheduled + unscheduled) == sorted(d.id for d in destinations)  # each exactly once


def test_same_result_when_run_twice(run):
    first, second = run(), run()
    assert first.itinerary == second.itinerary
    assert first.score == second.score


def test_budget_filled_in_and_matches_report(run):
    result = run(3, budget=50_000)
    it, report = result.itinerary, result.budget_report
    for plan, day in zip(it.days, report.days):
        assert plan.daily_budget_lkr == day.allocated_lkr
        assert plan.over_budget == day.over_budget
    assert it.total_cost_lkr == report.trip.total_planned_lkr
    assert it.over_budget == report.trip.over_budget


def test_score_matches_objective(run):
    result = run()
    assert result.score == score_plan(result.itinerary.days, result.itinerary.unscheduled,
                                      result.budget_report)


def test_budget_does_not_change_the_route(run):
    """Baseline has no feedback: the budget only changes the report, never the stops."""
    rich, poor = run(3, budget=1_000_000), run(3, budget=10_000)
    stops = lambda r: [[s.destination_id for s in d.stops] for d in r.itinerary.days]
    assert stops(rich) == stops(poor)
    assert poor.itinerary.over_budget and not rich.itinerary.over_budget
    assert poor.score.total < rich.score.total


def test_stops_carry_destination_scores(run, destinations):
    by_id = {d.id: d.score for d in destinations}
    for day in run().itinerary.days:
        for s in day.stops:
            assert s.score == by_id[s.destination_id]


def test_metrics_on_baseline(run):
    result = run(3, budget=100_000)
    it = result.itinerary
    m = evaluate_plan(it.days, it.unscheduled, result.budget_report, result.graph)
    assert m.conflicts == [] and m.conflict_rate == 0
    assert m.num_scheduled + m.num_unscheduled == 15
    assert m.travel_time_min == result.score.breakdown["travel_min"]
    assert m.within_budget == (not it.over_budget)
