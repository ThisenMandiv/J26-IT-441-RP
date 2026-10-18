"""Tests for src/graph.py. Uses the offline (haversine) matrix only."""

import networkx as nx
import pytest

from src import config
from src.distance import build_fake_matrix, start_location
from src.graph import build_graph, edge_weight
from src.loader import load_destinations
from src.models import TripRequest

START = config.START_NODE_ID


@pytest.fixture
def destinations():
    return load_destinations(config.DESTINATIONS_FILE)


@pytest.fixture
def trip():
    # Start in Colombo Fort
    return TripRequest(num_days=3, total_budget_lkr=100_000, start_lat=6.9344, start_lng=79.8428)


@pytest.fixture
def matrix(destinations, trip):
    return build_fake_matrix([start_location(trip), *destinations])


@pytest.fixture
def graph(destinations, matrix, trip):
    return build_graph(destinations, matrix, trip)


# ---------- Structure ----------

def test_node_count_is_destinations_plus_start(graph, destinations):
    assert graph.number_of_nodes() == len(destinations) + 1


def test_edge_count_is_every_ordered_pair_without_self_loops(graph, destinations):
    n = len(destinations) + 1
    assert graph.number_of_edges() == n * (n - 1)
    assert not any(u == v for u, v in graph.edges)


def test_graph_is_directed(graph):
    assert graph.is_directed()


def test_start_node_exists_at_trip_start(graph, trip):
    assert START in graph
    node = graph.nodes[START]
    assert node["kind"] == "start"
    assert (node["lat"], node["lng"]) == (trip.start_lat, trip.start_lng)
    assert node["cost_lkr"] == 0
    assert node["visit_duration_min"] == 0
    assert (node["opening_time"], node["closing_time"]) == (trip.day_start, trip.day_end)


def test_start_connects_both_ways_to_every_destination(graph, destinations):
    for d in destinations:
        assert graph.has_edge(START, d.id)
        assert graph.has_edge(d.id, START)


# ---------- Attributes ----------

def test_destination_node_attributes(graph, destinations):
    d = destinations[0]
    node = graph.nodes[d.id]
    assert node["kind"] == "destination"
    assert node["cost_lkr"] == d.cost_lkr
    assert node["visit_duration_min"] == d.visit_duration_min
    assert node["opening_time"] == d.opening_time
    assert node["closing_time"] == d.closing_time
    assert node["score"] == d.score


def test_edge_attributes_match_matrix(graph, matrix, destinations):
    a, b = destinations[0].id, destinations[1].id
    edge = graph.edges[a, b]
    assert edge["distance_km"] == matrix[a][b]["distance_km"]
    assert edge["duration_min"] == matrix[a][b]["duration_min"]
    assert edge["cost_lkr"] == pytest.approx(
        matrix[a][b]["distance_km"] * config.TRAVEL_COST_PER_KM_LKR, abs=0.01
    )
    assert edge["source"] == "haversine"


def test_custom_cost_per_km(destinations, matrix, trip):
    graph = build_graph(destinations, matrix, trip, cost_per_km=50)
    a, b = destinations[0].id, destinations[1].id
    assert graph.edges[a, b]["cost_lkr"] == pytest.approx(matrix[a][b]["distance_km"] * 50, abs=0.01)


# ---------- Errors ----------

def test_matrix_without_start_is_rejected(destinations, trip):
    matrix = build_fake_matrix(destinations)  # START missing
    with pytest.raises(ValueError, match="START"):
        build_graph(destinations, matrix, trip)


def test_reserved_start_id_is_rejected(destinations, matrix, trip):
    clash = destinations[0].model_copy(update={"id": START})
    with pytest.raises(ValueError, match="reserved"):
        build_graph([clash], matrix, trip)


# ---------- edge_weight ----------

EDGE = {"distance_km": 40.0, "duration_min": 90.0, "cost_lkr": 4000.0}


def test_edge_weight_formula():
    w = {"time": 0.6, "cost": 0.4}
    expected = (
        0.6 * 90.0 / config.EDGE_TIME_SCALE_MIN
        + 0.4 * 4000.0 / config.EDGE_COST_SCALE_LKR
    )
    assert edge_weight(EDGE, w) == pytest.approx(expected)


def test_edge_weight_changes_when_weights_change():
    time_only = edge_weight(EDGE, {"time": 1.0, "cost": 0.0})
    cost_only = edge_weight(EDGE, {"time": 0.0, "cost": 1.0})
    assert time_only != cost_only
    assert edge_weight(EDGE, {"time": 2.0, "cost": 0.0}) == pytest.approx(2 * time_only)


def test_edge_weight_defaults_come_from_config():
    assert edge_weight(EDGE) == pytest.approx(edge_weight(EDGE, config.EDGE_WEIGHTS))


def test_edge_weight_rejects_negative_weights():
    with pytest.raises(ValueError):
        edge_weight(EDGE, {"time": -1.0, "cost": 0.5})


def test_edge_weight_works_as_networkx_weight(graph, destinations):
    w = {"time": 1.0, "cost": 0.0}
    target = destinations[0].id
    length = nx.dijkstra_path_length(graph, START, target, weight=lambda u, v, d: edge_weight(d, w))
    assert length > 0
