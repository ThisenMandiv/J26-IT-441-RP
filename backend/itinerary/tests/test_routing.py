"""Tests for src/routing.py, checked against NetworkX's own Dijkstra."""

import math

import networkx as nx
import pytest

from src import config
from src.distance import build_fake_matrix, haversine_km, start_location
from src.graph import build_graph, edge_weight
from src.loader import load_destinations
from src.models import TripRequest
from src.routing import (
    NoPathError,
    astar,
    compare_algorithms,
    dijkstra,
    haversine_heuristic,
    shortest_path_matrix,
)

START = config.START_NODE_ID
TIME_ONLY = {"time": 1.0, "cost": 0.0}
COST_ONLY = {"time": 0.0, "cost": 1.0}
WEIGHT_SETS = [config.EDGE_WEIGHTS, TIME_ONLY, COST_ONLY]


def nx_weight(weights):
    return lambda u, v, d: edge_weight(d, weights)


# ---------- Graphs ----------

@pytest.fixture(scope="module")
def mock_graph():
    """The 15 mock destinations + START (complete graph, haversine matrix)."""
    destinations = load_destinations(config.DESTINATIONS_FILE)
    trip = TripRequest(num_days=3, total_budget_lkr=100_000, start_lat=6.9344, start_lng=79.8428)
    matrix = build_fake_matrix([start_location(trip), *destinations])
    return build_graph(destinations, matrix, trip)


def _road(graph, u, v, km, minutes, cost):
    graph.add_edge(u, v, distance_km=km, duration_min=minutes, cost_lkr=cost)


@pytest.fixture
def road_graph():
    """Small hand-made network (values invented for the test) where time and cost disagree.

    A -> C   expressway: fast (15 min) but tolled (4000 LKR)
    A -> B -> C  back road: slow (80 min) but cheaper (3600 LKR)
    C -> E   only road to E.   D: no roads in, so unreachable.
    Every edge is at least as long as the straight line and no faster than 100 km/h,
    so the A* heuristic stays admissible.
    """
    g = nx.DiGraph()
    coords = {"A": (7.0, 80.0), "B": (7.1, 80.1), "C": (7.0, 80.2), "D": (7.3, 80.3), "E": (7.0, 80.3)}
    for node, (lat, lng) in coords.items():
        g.add_node(node, lat=lat, lng=lng)
    _road(g, "A", "C", 25, 15, 4000)
    _road(g, "A", "B", 18, 40, 1800)
    _road(g, "B", "C", 18, 40, 1800)
    _road(g, "C", "E", 15, 20, 1500)
    _road(g, "D", "A", 55, 70, 5500)
    return g


# ---------- Agreement with NetworkX ----------

@pytest.mark.parametrize("weights", WEIGHT_SETS)
@pytest.mark.parametrize("algorithm", [dijkstra, astar])
def test_matches_networkx_on_mock_graph(mock_graph, algorithm, weights):
    for u in mock_graph.nodes:
        for v in mock_graph.nodes:
            expected = nx.dijkstra_path_length(mock_graph, u, v, weight=nx_weight(weights))
            assert algorithm(mock_graph, u, v, weights).total_weight == pytest.approx(expected)


@pytest.mark.parametrize("weights", WEIGHT_SETS)
@pytest.mark.parametrize("algorithm", [dijkstra, astar])
def test_matches_networkx_on_road_graph(road_graph, algorithm, weights):
    for u, v in [("A", "C"), ("A", "E"), ("B", "E"), ("D", "E")]:
        expected = nx.dijkstra_path_length(road_graph, u, v, weight=nx_weight(weights))
        assert algorithm(road_graph, u, v, weights).total_weight == pytest.approx(expected)


def test_path_weight_adds_up(road_graph):
    result = dijkstra(road_graph, "D", "E", COST_ONLY)
    edges = zip(result.path, result.path[1:])
    assert result.total_weight == pytest.approx(
        sum(edge_weight(road_graph.edges[u, v], COST_ONLY) for u, v in edges)
    )


# ---------- A* vs Dijkstra ----------

@pytest.mark.parametrize("weights", WEIGHT_SETS)
def test_astar_same_weight_and_no_more_expansions(mock_graph, weights):
    for u in mock_graph.nodes:
        for v in mock_graph.nodes:
            d = dijkstra(mock_graph, u, v, weights)
            a = astar(mock_graph, u, v, weights)
            assert a.total_weight == pytest.approx(d.total_weight)
            assert a.nodes_expanded <= d.nodes_expanded


def test_astar_expands_fewer_nodes_overall(mock_graph):
    pairs = [(u, v) for u in mock_graph.nodes for v in mock_graph.nodes if u != v]
    d = sum(dijkstra(mock_graph, u, v).nodes_expanded for u, v in pairs)
    a = sum(astar(mock_graph, u, v).nodes_expanded for u, v in pairs)
    assert a < d


@pytest.mark.parametrize("weights", WEIGHT_SETS)
def test_heuristic_never_overestimates(mock_graph, weights):
    for v in mock_graph.nodes:
        h = haversine_heuristic(mock_graph, v, weights)
        for u in mock_graph.nodes:
            true = nx.dijkstra_path_length(mock_graph, u, v, weight=nx_weight(weights))
            assert h(u) <= true + 1e-9


def test_heuristic_is_zero_at_target(mock_graph):
    assert haversine_heuristic(mock_graph, START)(START) == 0


# ---------- Edge cases ----------

@pytest.mark.parametrize("algorithm", [dijkstra, astar])
def test_unreachable_target_raises(road_graph, algorithm):
    with pytest.raises(NoPathError, match="no path from 'A' to 'D'"):
        algorithm(road_graph, "A", "D")


@pytest.mark.parametrize("algorithm", [dijkstra, astar])
def test_unknown_node_raises(road_graph, algorithm):
    with pytest.raises(KeyError, match="not in the graph"):
        algorithm(road_graph, "A", "Z")


@pytest.mark.parametrize("algorithm", [dijkstra, astar])
def test_source_equals_target(road_graph, algorithm):
    assert algorithm(road_graph, "A", "A") == (["A"], 0.0, 1)


# ---------- Weights change the route ----------

@pytest.mark.parametrize("algorithm", [dijkstra, astar])
def test_changing_weights_changes_path(road_graph, algorithm):
    assert algorithm(road_graph, "A", "C", TIME_ONLY).path == ["A", "C"]  # expressway
    assert algorithm(road_graph, "A", "C", COST_ONLY).path == ["A", "B", "C"]  # back road


# ---------- shortest_path_matrix ----------

def test_matrix_matches_networkx_all_pairs(mock_graph):
    result = shortest_path_matrix(mock_graph, COST_ONLY)
    expected = dict(nx.all_pairs_dijkstra_path_length(mock_graph, weight=nx_weight(COST_ONLY)))
    for u in mock_graph.nodes:
        for v in mock_graph.nodes:
            assert result[u][v]["weight"] == pytest.approx(expected[u][v])


def test_matrix_uses_paths_not_only_direct_edges(road_graph):
    result = shortest_path_matrix(road_graph, COST_ONLY)
    assert result["A"]["C"]["path"] == ["A", "B", "C"]
    assert result["A"]["C"]["weight"] < edge_weight(road_graph.edges["A", "C"], COST_ONLY)
    assert result["A"]["E"]["path"] == ["A", "B", "C", "E"]  # no direct edge at all


def test_matrix_unreachable_and_self(road_graph):
    result = shortest_path_matrix(road_graph)
    assert result["A"]["D"] == {"weight": math.inf, "path": []}
    assert result["A"]["A"] == {"weight": 0.0, "path": ["A"]}
    assert set(result) == set(road_graph.nodes)


# ---------- Benchmark ----------

def test_compare_algorithms_prints_and_returns(mock_graph, capsys):
    totals = compare_algorithms(mock_graph)
    out = capsys.readouterr().out
    assert "Dijkstra" in out and "A*" in out
    assert totals["A*"]["nodes_expanded"] <= totals["Dijkstra"]["nodes_expanded"]


def test_road_graph_is_admissible_by_construction(road_graph):
    """Guard for the fixture itself: edges respect the heuristic's best-case bounds."""
    for u, v, d in road_graph.edges(data=True):
        a, b = road_graph.nodes[u], road_graph.nodes[v]
        assert d["distance_km"] >= haversine_km(a["lat"], a["lng"], b["lat"], b["lng"])
        assert d["duration_min"] >= d["distance_km"] / config.MAX_PLAUSIBLE_SPEED_KMH * 60
        assert d["cost_lkr"] >= d["distance_km"] * config.MIN_TRAVEL_COST_PER_KM_LKR
