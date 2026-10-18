"""Tests for src/tsp.py on the mock data and on random (asymmetric) cost matrices."""

import itertools
import math
import random

import pytest

from src import config
from src.distance import build_fake_matrix, start_location
from src.graph import build_graph
from src.loader import load_destinations
from src.models import TripRequest
from src.routing import shortest_path_matrix
from src.tsp import (
    compare_orders,
    exact_best_order,
    nearest_neighbor_order,
    route_cost,
    two_opt,
)

START = config.START_NODE_ID


# ---------- Cost matrices ----------

def _matrix_for(destinations) -> dict:
    trip = TripRequest(num_days=3, total_budget_lkr=100_000, start_lat=6.9344, start_lng=79.8428)
    matrix = build_fake_matrix([start_location(trip), *destinations])
    return shortest_path_matrix(build_graph(destinations, matrix, trip))


@pytest.fixture(scope="module")
def destinations():
    return load_destinations(config.DESTINATIONS_FILE)


@pytest.fixture(scope="module")
def mock_costs(destinations):
    """Shortest-path costs for START + 8 mock destinations."""
    return _matrix_for(destinations[:8])


def random_costs(n: int, seed: int) -> dict:
    """START + n stops with random, asymmetric costs (u->v differs from v->u)."""
    rng = random.Random(seed)
    nodes = [START] + [f"S{i}" for i in range(n)]
    return {u: {v: {"weight": 0.0 if u == v else rng.uniform(1, 100)} for v in nodes} for u in nodes}


def brute_force_cost(costs: dict) -> float:
    stops = [n for n in costs if n != START]
    return min(route_cost([START, *p], costs) for p in itertools.permutations(stops))


def assert_valid_order(order, costs):
    """Starts at START and visits every other node exactly once."""
    assert order[0] == START
    assert sorted(order[1:]) == sorted(n for n in costs if n != START)


# ---------- Valid orders ----------

def test_nearest_neighbor_visits_every_stop_once(mock_costs):
    assert_valid_order(nearest_neighbor_order(mock_costs, START), mock_costs)


def test_two_opt_visits_every_stop_once(mock_costs):
    order, _ = two_opt(nearest_neighbor_order(mock_costs, START), mock_costs)
    assert_valid_order(order, mock_costs)


def test_exact_visits_every_stop_once(mock_costs):
    order, _ = exact_best_order(mock_costs, START)
    assert_valid_order(order, mock_costs)


@pytest.mark.parametrize("seed", range(10))
def test_orders_valid_on_random_matrices(seed):
    costs = random_costs(7, seed)
    nn = nearest_neighbor_order(costs)
    assert_valid_order(nn, costs)
    assert_valid_order(two_opt(nn, costs)[0], costs)
    assert_valid_order(exact_best_order(costs)[0], costs)


# ---------- Nearest neighbour ----------

def test_nearest_neighbor_picks_cheapest_next(mock_costs):
    order = nearest_neighbor_order(mock_costs, START)
    for i in range(1, len(order)):
        here, chosen, later = order[i - 1], order[i], order[i:]
        assert all(mock_costs[here][chosen]["weight"] <= mock_costs[here][s]["weight"] for s in later)


def test_nearest_neighbor_respects_stops_subset(mock_costs, destinations):
    subset = [d.id for d in destinations[:3]]
    order = nearest_neighbor_order(mock_costs, START, subset)
    assert order[0] == START and sorted(order[1:]) == sorted(subset)


# ---------- 2-opt ----------

def test_two_opt_never_worse_than_nearest_neighbor(mock_costs):
    nn = nearest_neighbor_order(mock_costs, START)
    _, cost = two_opt(nn, mock_costs)
    assert cost <= route_cost(nn, mock_costs) + 1e-9


@pytest.mark.parametrize("seed", range(20))
def test_two_opt_never_worse_on_random_matrices(seed):
    costs = random_costs(8, seed)
    nn = nearest_neighbor_order(costs)
    _, cost = two_opt(nn, costs)
    assert cost <= route_cost(nn, costs) + 1e-9


def test_two_opt_returned_cost_matches_order(mock_costs):
    order, cost = two_opt(nearest_neighbor_order(mock_costs, START), mock_costs)
    assert cost == pytest.approx(route_cost(order, mock_costs))


def test_two_opt_fixes_a_bad_order(mock_costs):
    worst = [START, *sorted((n for n in mock_costs if n != START), reverse=True)]
    _, cost = two_opt(worst, mock_costs)
    assert cost < route_cost(worst, mock_costs)


# ---------- Exact ----------

@pytest.mark.parametrize("n", range(1, 7))
def test_exact_matches_brute_force(n):
    costs = random_costs(n, seed=n)
    order, cost = exact_best_order(costs)
    assert cost == pytest.approx(brute_force_cost(costs))
    assert cost == pytest.approx(route_cost(order, costs))


@pytest.mark.parametrize("seed", range(10))
def test_exact_is_lower_bound_for_heuristics(seed):
    costs = random_costs(8, seed)
    nn = nearest_neighbor_order(costs)
    _, opt2_cost = two_opt(nn, costs)
    _, exact_cost = exact_best_order(costs)
    assert exact_cost <= opt2_cost + 1e-9 <= route_cost(nn, costs) + 2e-9


def test_exact_rejects_too_many_stops():
    with pytest.raises(ValueError, match="at most 10"):
        exact_best_order(random_costs(11, seed=0))


def test_exact_handles_ten_stops():
    order, cost = exact_best_order(random_costs(10, seed=0))
    assert len(order) == 11 and math.isfinite(cost)


# ---------- Heuristic = exact on tiny cases ----------

@pytest.mark.parametrize("seed", range(10))
@pytest.mark.parametrize("n", [1, 2])
def test_heuristic_equals_exact_on_tiny_random(n, seed):
    """With <= 2 stops, one 2-opt reversal covers every possible order."""
    costs = random_costs(n, seed)
    _, heuristic = two_opt(nearest_neighbor_order(costs), costs)
    assert heuristic == pytest.approx(exact_best_order(costs)[1])


def test_heuristic_equals_exact_on_tiny_mock_case(destinations):
    """Sigiriya, Kandy, Galle from Colombo: 2-opt finds the optimum."""
    by_id = {d.id: d for d in destinations}
    costs = _matrix_for([by_id["D01"], by_id["D02"], by_id["D03"]])
    order, heuristic = two_opt(nearest_neighbor_order(costs), costs)
    exact_order, exact = exact_best_order(costs)
    assert heuristic == pytest.approx(exact)
    assert order == exact_order


def test_two_opt_can_stop_at_local_optimum(destinations):
    """Known limit, kept as a record: from Colombo via Pinnawala, Polonnaruwa, Galle,
    the optimum moves Galle to the front. No single segment reversal does that, so
    2-opt stops about 15% above the optimum. This is why exact_best_order exists."""
    by_id = {d.id: d for d in destinations}
    costs = _matrix_for([by_id["D13"], by_id["D12"], by_id["D03"]])
    order, heuristic = two_opt(nearest_neighbor_order(costs), costs)
    exact_order, exact = exact_best_order(costs)
    assert order == [START, "D13", "D12", "D03"]
    assert exact_order == [START, "D03", "D13", "D12"]
    assert heuristic > exact * 1.10


# ---------- Empty and single stop ----------

@pytest.fixture
def start_only():
    return {START: {START: {"weight": 0.0}}}


def test_no_stops(start_only):
    assert nearest_neighbor_order(start_only) == [START]
    assert two_opt([START], start_only) == ([START], 0)
    assert exact_best_order(start_only) == ([START], 0.0)


def test_empty_stops_list(mock_costs):
    assert nearest_neighbor_order(mock_costs, START, []) == [START]
    assert exact_best_order(mock_costs, START, []) == ([START], 0.0)


def test_single_stop():
    costs = random_costs(1, seed=0)
    expected = costs[START]["S0"]["weight"]
    assert nearest_neighbor_order(costs) == [START, "S0"]
    assert two_opt([START, "S0"], costs) == ([START, "S0"], expected)
    assert exact_best_order(costs) == ([START, "S0"], expected)


# ---------- Input checks ----------

def test_unknown_start_raises(mock_costs):
    with pytest.raises(KeyError, match="not in the cost matrix"):
        nearest_neighbor_order(mock_costs, "NOWHERE")


def test_start_in_stops_raises(mock_costs):
    with pytest.raises(ValueError, match="must not include the start"):
        nearest_neighbor_order(mock_costs, START, [START])


def test_duplicate_stops_raise(mock_costs, destinations):
    with pytest.raises(ValueError, match="duplicates"):
        exact_best_order(mock_costs, START, [destinations[0].id] * 2)


# ---------- Comparison ----------

def test_compare_orders_prints_all_three(mock_costs, capsys):
    results = compare_orders(mock_costs, START)
    out = capsys.readouterr().out
    for name in ("nearest_neighbor", "two_opt", "exact"):
        assert name in out
    assert results["exact"]["cost"] <= results["two_opt"]["cost"] + 1e-9
