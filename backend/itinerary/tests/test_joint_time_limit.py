"""Tests for the optional time limit of src/joint.optimize_joint (used by the HTTP API)."""

import pytest

from src import config
from src.joint import optimize_joint
from src.loader import load_destinations
from src.models import TripRequest

ITERATIONS = 300  # keeps the suite fast


@pytest.fixture(scope="module")
def inputs(tmp_path_factory):
    trip = TripRequest(num_days=3, total_budget_lkr=100_000, start_lat=6.9344, start_lng=79.8428)
    return load_destinations(config.DESTINATIONS_FILE), trip, tmp_path_factory.mktemp("cache")


def plan(result) -> list[list[str]]:
    return [[s.destination_id for s in d.stops] for d in result.itinerary.days]


def test_no_limit_is_the_default_and_never_times_out(inputs):
    places, trip, cache = inputs
    assert optimize_joint(places, trip, max_iterations=ITERATIONS, cache_dir=cache).timed_out is False


def test_a_limit_that_is_not_reached_changes_nothing(inputs):
    places, trip, cache = inputs
    free = optimize_joint(places, trip, max_iterations=ITERATIONS, cache_dir=cache)
    capped = optimize_joint(places, trip, max_iterations=ITERATIONS, cache_dir=cache, time_limit_s=600)
    assert not capped.timed_out
    assert plan(capped) == plan(free) and capped.score == free.score and capped.stats == free.stats


def test_a_reached_limit_returns_the_best_plan_so_far(inputs):
    places, trip, cache = inputs
    result = optimize_joint(places, trip, max_iterations=ITERATIONS, cache_dir=cache, time_limit_s=1e-9)
    assert result.timed_out
    assert result.score.total >= result.baseline.score.total  # still never below sequential
    assert plan(result) == plan(result.baseline)  # no time to search: the sequential plan
