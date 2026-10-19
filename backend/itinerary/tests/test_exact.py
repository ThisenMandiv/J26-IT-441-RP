"""Tests for src/exact.py: the exact benchmark (best plan under the objective, small trips)."""

import itertools
from datetime import time

import pytest

from src import config
from src.budget import allocate_budget, check_overruns
from src.exact import EXACT_REASON, exact_benchmark
from src.joint import optimize_joint
from src.loader import load_destinations
from src.models import Destination, TripRequest, UnscheduledStop
from src.objective import score_plan
from src.scheduler import schedule_fixed, validate_opening_hours

COLOMBO = (6.9344, 79.8428)


def trip(num_days=1, budget=100_000.0) -> TripRequest:
    return TripRequest(num_days=num_days, total_budget_lkr=budget,
                       start_lat=COLOMBO[0], start_lng=COLOMBO[1])


def place(id, km_north, km_east=0.0, cost=1000, score=0.5, visit=120,
          opening=time(6, 0), closing=time(20, 0)) -> Destination:
    """Invented place near Colombo."""
    return Destination(id=id, name=f"Place {id}", lat=COLOMBO[0] + km_north / 111,
                       lng=COLOMBO[1] + km_east / 111, category="test", cost_lkr=cost,
                       visit_duration_min=visit, opening_time=opening, closing_time=closing, score=score)


def ids(itinerary) -> list[list[str]]:
    return [[s.destination_id for s in d.stops] for d in itinerary.days]


@pytest.fixture(scope="module")
def cache_dir(tmp_path_factory):
    return tmp_path_factory.mktemp("cache")


# ---------- Brute force: try literally every plan, no pruning ----------

def brute_force_best(graph, t: TripRequest, weights) -> float:
    """Every subset, every order, every split into days. Only for 4-5 places."""
    places = [n for n in graph.nodes if n != config.START_NODE_ID]
    best = -float("inf")
    for k in range(len(places) + 1):
        for perm in itertools.permutations(places, k):
            # cut positions split perm into num_days consecutive (possibly empty) days
            for cuts in itertools.combinations_with_replacement(range(k + 1), t.num_days - 1):
                bounds = [0, *cuts, k]
                orders = [list(perm[a:b]) for a, b in zip(bounds, bounds[1:])]
                days = schedule_fixed(orders, graph, t)
                if days is None:
                    continue
                left = [UnscheduledStop(destination_id=p, name=p, reason="x") for p in places if p not in perm]
                report = check_overruns(days, allocate_budget(days, t))
                best = max(best, score_plan(days, left, report, weights).total)
    return best


SMALL_CASES = {
    "mixed hours, 2 days": ([place("A", 5, score=0.9), place("B", 20, cost=8000, score=0.3),
                             place("C", 10, 10, opening=time(13, 0)), place("D", 30, visit=240, score=0.8)],
                            trip(2)),
    "tight budget, 1 day": ([place("A", 5, cost=4000, score=0.9), place("B", 15, cost=6000),
                             place("C", 25, cost=0, score=0.4), place("D", 8, 8, closing=time(11, 0))],
                            trip(1, budget=8000)),
}


@pytest.mark.parametrize("weight_name", list(config.EVALUATION_WEIGHT_SETTINGS))
@pytest.mark.parametrize("case", list(SMALL_CASES))
def test_matches_brute_force(case, weight_name, cache_dir):
    dests, t = SMALL_CASES[case]
    weights = config.EVALUATION_WEIGHT_SETTINGS[weight_name]
    result = exact_benchmark(dests, t, weights, cache_dir=cache_dir)
    assert result.score.total == pytest.approx(brute_force_best(result.graph, t, weights), abs=1e-6)


# ---------- Properties ----------

@pytest.fixture(scope="module")
def eight_places():
    """The 8 highest-scored mock places (the largest size the benchmark allows)."""
    dests = load_destinations(config.DESTINATIONS_FILE)
    return sorted(dests, key=lambda d: d.score, reverse=True)[:8]


@pytest.mark.parametrize("num_days", [1, 3])
def test_exact_at_least_joint_and_sequential(eight_places, cache_dir, num_days):
    t = trip(num_days)
    exact = exact_benchmark(eight_places, t, cache_dir=cache_dir)
    joint = optimize_joint(eight_places, t, max_iterations=300, cache_dir=cache_dir)
    assert exact.score.total >= joint.score.total - 1e-9 >= joint.baseline.score.total - 1e-9


def test_plan_is_valid_and_consistent(eight_places, cache_dir):
    result = exact_benchmark(eight_places, trip(3), cache_dir=cache_dir)
    it = result.itinerary
    assert validate_opening_hours(it.days, result.graph) == []
    assert result.score == score_plan(it.days, it.unscheduled, result.budget_report)
    scheduled = [s for d in ids(it) for s in d]
    assert sorted(scheduled + [u.destination_id for u in it.unscheduled]) == sorted(d.id for d in eight_places)
    assert all(u.reason == EXACT_REASON for u in it.unscheduled)
    assert result.states_explored > 0


def test_drops_a_place_that_breaks_the_budget(cache_dir):
    """X costs 20,000 LKR on a 10,000 LKR budget and scores low: the best plan leaves it out."""
    dests = [place("A", 3, score=0.9), place("B", 6, score=0.8), place("X", 9, cost=20_000, score=0.2)]
    result = exact_benchmark(dests, trip(1, budget=10_000), cache_dir=cache_dir)
    assert sorted(ids(result.itinerary)[0]) == ["A", "B"]
    assert not result.itinerary.over_budget


def test_too_many_places_raises(cache_dir):
    dests = [place(f"P{i}", i) for i in range(config.EXACT_MAX_PLACES + 1)]
    with pytest.raises(ValueError, match="at most"):
        exact_benchmark(dests, trip(), cache_dir=cache_dir)
