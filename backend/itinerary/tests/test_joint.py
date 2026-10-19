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
    """The log is the winning restart's improvements, starting from that restart's start plan."""
    result = mock_runs[3]
    scores = [result.start_score] + [m.score_after for m in result.moves]
    assert scores == sorted(scores) and len(set(scores)) == len(scores)
    assert scores[-1] == result.score.total
    assert all(1 <= m.iteration <= ITERATIONS for m in result.moves)
    assert 0 <= result.restart < config.JOINT_RESTARTS
    if result.restart == 0:
        assert result.start_score == result.baseline.score.total


def test_zero_iterations_returns_sequential_plan(mock_destinations, cache_dir):
    result = optimize_joint(mock_destinations, trip(3), max_iterations=0, restarts=1, cache_dir=cache_dir)
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


# ---------- Restarts and simulated annealing ----------

def test_more_restarts_never_score_lower(mock_destinations, cache_dir):
    """Restart 0 uses the random stream first, so it is identical in both runs; extra
    restarts can only replace its result with a strictly better one."""
    one = optimize_joint(mock_destinations, trip(3), max_iterations=300, restarts=1, cache_dir=cache_dir)
    many = optimize_joint(mock_destinations, trip(3), max_iterations=300, restarts=4, cache_dir=cache_dir)
    assert many.score.total >= one.score.total


@pytest.mark.parametrize("anneal", [False, True])
def test_hill_climbing_and_annealing_both_valid(mock_destinations, cache_dir, anneal):
    result = optimize_joint(mock_destinations, trip(3), max_iterations=300, anneal=anneal,
                            cache_dir=cache_dir)
    assert result.score.total >= result.baseline.score.total
    assert validate_opening_hours(result.itinerary.days, result.graph) == []
    assert result.score == score_plan(result.itinerary.days, result.itinerary.unscheduled,
                                      result.budget_report)


def test_accept_rule():
    import random

    from src.joint import _accept, _temperature
    rng = random.Random(0)
    assert _accept(0.5, 1, 100, anneal=False, rng=rng)  # better: always
    assert not _accept(-0.5, 1, 100, anneal=False, rng=rng)  # hill climbing: never worse
    assert not _accept(0.0, 1, 100, anneal=False, rng=rng)  # ... nor equal
    assert _temperature(1, 100) == pytest.approx(config.JOINT_ANNEAL_START_TEMP)
    assert _temperature(100, 100) == pytest.approx(config.JOINT_ANNEAL_END_TEMP)
    # annealing: a small loss is often accepted early, a big loss almost never late
    early = sum(_accept(-0.5, 1, 100, True, rng) for _ in range(1000))
    late = sum(_accept(-0.5, 100, 100, True, rng) for _ in range(1000))
    assert early > 600 and late == 0


def test_restart_from_random_order_can_win(mock_destinations, cache_dir):
    """Across a few seeds at least one winning plan comes from a random restart,
    so the restarts do real work (and joint still never drops below sequential)."""
    results = [optimize_joint(mock_destinations, trip(3), max_iterations=200, seed=s, cache_dir=cache_dir)
               for s in range(4)]
    assert all(r.score.total >= r.baseline.score.total for r in results)
    assert any(r.restart > 0 for r in results)


# ---------- Search log (RestartStats) ----------

def test_search_log_has_one_entry_per_restart(mock_runs):
    for result in mock_runs.values():
        assert [s.restart for s in result.stats] == list(range(config.JOINT_RESTARTS))
        assert all(s.iterations == ITERATIONS for s in result.stats)


def test_search_log_counts_add_up(mock_runs):
    for result in mock_runs.values():
        for s in result.stats:
            assert s.tried <= s.iterations
            assert s.infeasible + s.accepted <= s.tried  # accepted ones were feasible
            assert s.accepted_worse <= s.accepted and s.improvements <= s.accepted
            assert 0 <= s.last_improvement <= s.iterations
            assert (s.last_improvement == 0) == (s.improvements == 0)
            assert s.best_score >= s.start_score
            per_kind = [sum(c[k] for c in s.by_kind.values()) for k in range(4)]
            assert per_kind == [s.tried, s.tried - s.infeasible, s.accepted, s.improvements]


def test_search_log_of_winner_matches_move_log(mock_runs):
    for result in mock_runs.values():
        won = next(s for s in result.stats if s.restart == result.restart)
        assert won.improvements == len(result.moves)
        assert won.last_improvement == (result.moves[-1].iteration if result.moves else 0)
        assert won.start_score == result.start_score
