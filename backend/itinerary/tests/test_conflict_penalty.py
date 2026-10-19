"""Tests for the opening-hour conflict penalty in src/objective.py (version 3).

1. A stop that breaks opening hours costs config.CONFLICT_PENALTY.
2. The penalty is big enough that visiting a closed place never pays.
3. Sequential, joint and exact never have conflicts, so their scores are exactly
   what they would be without the penalty (checked on the real evaluation scenarios).
4. The naive baseline no longer beats them by visiting closed places.
"""

from datetime import time

import pytest

from src import config
from src.budget import allocate_budget, check_overruns
from src.distance import build_fake_matrix, start_location
from src.exact import exact_benchmark
from src.graph import build_graph
from src.joint import optimize_joint
from src.models import DayPlan, Destination, Stop, TripRequest
from src.objective import score_plan
from src.pipeline import run_naive, run_sequential
from src.scenarios import build_scenarios

COLOMBO = (6.9344, 79.8428)


# ---------- Hand-built plan (invented values) ----------

def trip() -> TripRequest:
    return TripRequest(num_days=1, total_budget_lkr=100_000, start_lat=COLOMBO[0], start_lng=COLOMBO[1])


@pytest.fixture
def graph():
    """One place open 09:00-12:00 with a 60 min visit."""
    place = Destination(id="A", name="Place A", lat=COLOMBO[0] + 0.02, lng=COLOMBO[1], category="test",
                        cost_lkr=0, visit_duration_min=60, opening_time=time(9, 0),
                        closing_time=time(12, 0), score=0.8)
    t = trip()
    return build_graph([place], build_fake_matrix([start_location(t), place]), t)


def visit(arrival: time, departure: time) -> list[DayPlan]:
    stop = Stop(destination_id="A", name="Place A", arrival_time=arrival, departure_time=departure,
                travel_time_min=5, travel_cost_lkr=0, entry_cost_lkr=0, score=0.8)
    return [DayPlan(day=1, stops=[stop])]


def score(days, graph=None, weights=config.OBJECTIVE_WEIGHTS):
    report = check_overruns(days, allocate_budget(days, trip()))
    return score_plan(days, [], report, weights, graph)


def test_valid_visit_has_no_penalty(graph):
    result = score(visit(time(10, 0), time(11, 0)), graph)
    assert result.breakdown["conflicting_stops"] == 0
    assert result.breakdown["terms"]["conflict"] == 0


def test_visit_to_closed_place_is_penalised(graph):
    ok = score(visit(time(10, 0), time(11, 0)), graph)
    closed = score(visit(time(13, 0), time(14, 0)), graph)  # place closed at 12:00
    assert closed.breakdown["conflicting_stops"] == 1
    assert closed.breakdown["terms"]["conflict"] == -config.CONFLICT_PENALTY
    assert closed.total == pytest.approx(ok.total - config.CONFLICT_PENALTY)


def test_without_graph_hours_are_not_checked(graph):
    """graph=None is only for hand-built test plans: the penalty is then skipped."""
    closed = visit(time(13, 0), time(14, 0))
    assert score(closed).breakdown["conflicting_stops"] == 0
    assert score(closed).total == pytest.approx(score(closed, graph).total + config.CONFLICT_PENALTY)


@pytest.mark.parametrize("weight_name", list(config.EVALUATION_WEIGHT_SETTINGS))
def test_penalty_outweighs_anything_one_visit_can_earn(weight_name):
    """Max gain of one visit: full score (1.0), one fewer unscheduled, one fewer coverage shortfall.
    The sensitivity check raises COVERAGE_PENALTY to 40, so that case must hold too."""
    w = config.EVALUATION_WEIGHT_SETTINGS[weight_name]
    for coverage in (config.COVERAGE_PENALTY, 40.0):
        assert config.CONFLICT_PENALTY > w["score"] * 1.0 + w["unscheduled"] + coverage


def test_visit_to_closed_place_scores_below_leaving_it_out(graph):
    """A conflicting visit must never be worth more than not going at all."""
    from src.models import UnscheduledStop
    left = [UnscheduledStop(destination_id="A", name="Place A", reason="test")]
    empty = [DayPlan(day=1)]
    report = check_overruns(empty, allocate_budget(empty, trip()))
    skipped = score_plan(empty, left, report, config.OBJECTIVE_WEIGHTS, graph)  # also pays coverage
    assert score(visit(time(13, 0), time(14, 0)), graph).total < skipped.total


# ---------- Real scenarios: only naive is affected ----------

@pytest.fixture(scope="module")
def cache(tmp_path_factory):
    return tmp_path_factory.mktemp("cache")


def without_penalty(result, weights):
    """Score the same plan as if CONFLICT_PENALTY did not exist."""
    it = result.itinerary
    raw = score_plan(it.days, it.unscheduled, result.budget_report, weights, result.graph)
    return raw.total - raw.breakdown["terms"]["conflict"]


@pytest.mark.parametrize("sid", [s.id for s in build_scenarios()])
def test_sequential_unaffected(sid, cache):
    sc = next(s for s in build_scenarios() if s.id == sid)
    seq = run_sequential(sc.destinations, sc.trip, cache_dir=cache)
    assert seq.score.breakdown["conflicting_stops"] == 0
    assert seq.score.total == pytest.approx(without_penalty(seq, config.OBJECTIVE_WEIGHTS))


@pytest.mark.parametrize("sid", ["S11", "S12", "S14", "S15"])  # the scenarios where naive has conflicts
def test_joint_unaffected(sid, cache):
    sc = next(s for s in build_scenarios() if s.id == sid)
    jnt = optimize_joint(sc.destinations, sc.trip, max_iterations=150, cache_dir=cache)
    assert jnt.score.breakdown["conflicting_stops"] == 0
    assert jnt.score.total == pytest.approx(without_penalty(jnt, config.OBJECTIVE_WEIGHTS))


def test_joint_search_is_identical_with_and_without_penalty(cache, monkeypatch):
    """The joint optimizer rejects conflicting candidates before scoring them, so the penalty
    cannot change which moves it makes: same plan, same score, same moves."""
    sc = next(s for s in build_scenarios() if s.id == "S14")
    with_p = optimize_joint(sc.destinations, sc.trip, max_iterations=150, cache_dir=cache)
    monkeypatch.setattr(config, "CONFLICT_PENALTY", 0.0)
    without_p = optimize_joint(sc.destinations, sc.trip, max_iterations=150, cache_dir=cache)
    assert with_p.score == without_p.score and with_p.moves == without_p.moves


@pytest.mark.parametrize("sid", ["S06", "S09", "S11"])  # small enough for the exact benchmark
def test_exact_unaffected(sid, cache):
    sc = next(s for s in build_scenarios() if s.id == sid)
    ex = exact_benchmark(sc.destinations, sc.trip, cache_dir=cache)
    assert ex.score.breakdown["conflicting_stops"] == 0
    assert ex.score.total == pytest.approx(without_penalty(ex, config.OBJECTIVE_WEIGHTS))


@pytest.mark.parametrize("sid", ["S11", "S12", "S13", "S14", "S15"])
def test_naive_no_longer_beats_sequential_by_visiting_closed_places(sid, cache):
    """In version 2, naive scored above sequential in these runs only because it ignored hours."""
    sc = next(s for s in build_scenarios() if s.id == sid)
    naive = run_naive(sc.destinations, sc.trip, cache_dir=cache)
    seq = run_sequential(sc.destinations, sc.trip, cache_dir=cache)
    assert naive.conflicts  # naive really does break opening hours here
    assert naive.score.breakdown["conflicting_stops"] >= 1
    assert naive.score.total < seq.score.total
