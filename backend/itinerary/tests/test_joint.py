"""Tests for src/joint.py: hill climbing on the joint objective."""

from datetime import time

import pytest

from src import config
from src.joint import DROPPED_REASON, optimize_joint
from src.loader import load_destinations
from src.models import Destination, TripRequest
from src.objective import score_plan
from src.scheduler import validate_opening_hours

COLOMBO = (6.9344, 79.8428)
ITERATIONS = 500  # enough for these cases, keeps the suite fast


def trip(num_days=3, budget=100_000.0) -> TripRequest:
    return TripRequest(num_days=num_days, total_budget_lkr=budget,
                       start_lat=COLOMBO[0], start_lng=COLOMBO[1])


def place(id, km_north, cost, score) -> Destination:
    """Invented place a short drive north of the start, open all day, 60 min visit."""
    return Destination(id=id, name=f"Place {id}", lat=COLOMBO[0] + km_north / 111, lng=COLOMBO[1],
                       category="test", cost_lkr=cost, visit_duration_min=60,
                       opening_time=time(6, 0), closing_time=time(20, 0), score=score)


def ids(itinerary) -> list[str]:
    return [s.destination_id for d in itinerary.days for s in d.stops]


@pytest.fixture(scope="module")
def mock_destinations():
    return load_destinations(config.DESTINATIONS_FILE)


@pytest.fixture(scope="module")
def cache_dir(tmp_path_factory):
    return tmp_path_factory.mktemp("cache")


@pytest.fixture(scope="module")
def mock_runs(mock_destinations, cache_dir):
    """One joint run per trip length on the 15-place mock data."""
    return {n: optimize_joint(mock_destinations, trip(n), max_iterations=ITERATIONS, cache_dir=cache_dir)
            for n in (1, 3, 7)}


# ---------- Never worse than sequential ----------

@pytest.mark.parametrize("num_days", [1, 3, 7])
def test_joint_score_never_below_sequential(mock_runs, num_days):
    result = mock_runs[num_days]
    assert result.score.total >= result.baseline.score.total


def test_joint_improves_on_mock_data(mock_runs):
    result = mock_runs[3]
    assert result.score.total > result.baseline.score.total
    assert result.moves  # at least one change was accepted


def test_move_log_scores_strictly_increase(mock_runs):
    result = mock_runs[3]
    scores = [result.baseline.score.total] + [m.score_after for m in result.moves]
    assert scores == sorted(scores) and len(set(scores)) == len(scores)
    assert scores[-1] == result.score.total
    assert all(1 <= m.iteration <= ITERATIONS for m in result.moves)


def test_zero_iterations_returns_sequential_plan(mock_destinations, cache_dir):
    result = optimize_joint(mock_destinations, trip(3), max_iterations=0, cache_dir=cache_dir)
    assert result.itinerary == result.baseline.itinerary
    assert result.score == result.baseline.score
    assert result.moves == []


# ---------- Repeatable ----------

def test_same_seed_same_result(mock_destinations, cache_dir):
    first, second = (optimize_joint(mock_destinations, trip(3), max_iterations=ITERATIONS, seed=7,
                                    cache_dir=cache_dir) for _ in range(2))
    assert first.itinerary == second.itinerary
    assert first.score == second.score
    assert first.moves == second.moves


# ---------- Valid plan ----------

@pytest.mark.parametrize("num_days", [1, 3, 7])
def test_final_plan_has_no_opening_hour_conflicts(mock_runs, num_days):
    result = mock_runs[num_days]
    assert validate_opening_hours(result.itinerary.days, result.graph) == []


@pytest.mark.parametrize("num_days", [1, 3, 7])
def test_every_place_scheduled_or_unscheduled(mock_runs, mock_destinations, num_days):
    it = mock_runs[num_days].itinerary
    unscheduled = [u.destination_id for u in it.unscheduled]
    assert sorted(ids(it) + unscheduled) == sorted(d.id for d in mock_destinations)


@pytest.mark.parametrize("num_days", [1, 3, 7])
def test_itinerary_fields_match_score_and_report(mock_runs, num_days):
    result = mock_runs[num_days]
    it, report = result.itinerary, result.budget_report
    assert [d.day for d in it.days] == list(range(1, num_days + 1))
    assert all(s.departure_time <= config.DEFAULT_DAY_END for d in it.days for s in d.stops)
    assert it.total_cost_lkr == report.trip.total_planned_lkr
    assert [d.daily_budget_lkr for d in it.days] == [d.allocated_lkr for d in report.days]
    assert result.score == score_plan(it.days, it.unscheduled, report)


# ---------- Budget: the joint model reacts, the baseline only reports ----------

@pytest.fixture
def tight_case(cache_dir):
    """A and B are cheap and well liked; X costs 20,000 LKR and scores 0.2.
    All three fit in one day, but the 10,000 LKR budget only covers A and B."""
    dests = [place("A", 3, 1000, 0.9), place("B", 6, 1000, 0.8), place("X", 9, 20_000, 0.2)]
    return dests, trip(num_days=1, budget=10_000)


def test_tight_budget_joint_avoids_overrun(tight_case, cache_dir):
    dests, t = tight_case
    result = optimize_joint(dests, t, max_iterations=ITERATIONS, cache_dir=cache_dir)
    seq = result.baseline
    assert seq.itinerary.over_budget and seq.score.breakdown["overrun_lkr"] > 0
    assert not result.itinerary.over_budget
    assert result.score.breakdown["overrun_lkr"] == 0
    assert ids(result.itinerary) == ["A", "B"]
    (dropped,) = result.itinerary.unscheduled
    assert dropped.destination_id == "X" and dropped.reason == DROPPED_REASON


def test_changing_a_weight_changes_the_result(tight_case, cache_dir):
    """If money is not penalised, keeping the pricey place X scores higher than dropping it."""
    dests, t = tight_case
    no_money = {**config.OBJECTIVE_WEIGHTS, "spend": 0.0, "overrun": 0.0}
    default = optimize_joint(dests, t, max_iterations=ITERATIONS, cache_dir=cache_dir)
    changed = optimize_joint(dests, t, weights=no_money, max_iterations=ITERATIONS, cache_dir=cache_dir)
    assert "X" not in ids(default.itinerary)
    assert "X" in ids(changed.itinerary)
    assert default.itinerary != changed.itinerary


def test_unscheduled_place_is_inserted_when_it_helps(mock_runs):
    """On the 3-day mock trip, joint re-inserts a place sequential could not fit."""
    result = mock_runs[3]
    assert any(m.description.startswith("insert") for m in result.moves)
    assert len(ids(result.itinerary)) > len(ids(result.baseline.itinerary))
