"""Weighted travel graph over the destinations and the trip's start point (WBS 3.3).

build_graph() turns the distance/time matrix into a NetworkX DiGraph:
- nodes: one per destination plus a START node at the trip's start coordinates
- edges: every ordered pair of different nodes (directed, because Google
  travel times can differ A->B vs B->A)

edge_weight() folds an edge's time and cost into one number. The weights come
from src/config.py so Dijkstra/A*/TSP (and a later ML step) change them in one place.
"""

from collections.abc import Mapping, Sequence

import networkx as nx

from src import config
from src.distance import Matrix
from src.models import Destination, TripRequest


def _destination_attrs(dest: Destination) -> dict:
    """Node data for a destination."""
    return {
        "kind": "destination",
        "name": dest.name,
        "lat": dest.lat,
        "lng": dest.lng,
        "cost_lkr": dest.cost_lkr,
        "visit_duration_min": dest.visit_duration_min,
        "opening_time": dest.opening_time,
        "closing_time": dest.closing_time,
        "score": dest.score,
    }


def _start_attrs(trip: TripRequest) -> dict:
    """Node data for START: nothing to pay or visit; 'open' for the traveller's day."""
    return {
        "kind": "start",
        "name": "Start",
        "lat": trip.start_lat,
        "lng": trip.start_lng,
        "cost_lkr": 0.0,
        "visit_duration_min": 0,
        "opening_time": trip.day_start,
        "closing_time": trip.day_end,
        "score": 0.0,
    }


def _edge_attrs(entry: dict, cost_per_km: float) -> dict:
    """Edge data from one matrix entry. Travel cost = distance x cost per km (APPROX rate)."""
    return {
        "distance_km": entry["distance_km"],
        "duration_min": entry["duration_min"],
        "cost_lkr": round(entry["distance_km"] * cost_per_km, 2),
        "source": entry["source"],
    }


def build_graph(
    destinations: Sequence[Destination],
    matrix: Matrix,
    trip_request: TripRequest,
    cost_per_km: float = config.TRAVEL_COST_PER_KM_LKR,
) -> nx.DiGraph:
    """Directed graph of START + destinations, with travel data on every edge.

    The matrix must contain START (use distance.get_matrix_with_start).
    """
    start_id = config.START_NODE_ID
    graph = nx.DiGraph()
    graph.add_node(start_id, **_start_attrs(trip_request))
    for dest in destinations:
        if dest.id == start_id:
            raise ValueError(f"destination id {start_id!r} is reserved for the start point")
        graph.add_node(dest.id, **_destination_attrs(dest))

    for origin in graph.nodes:
        for target in graph.nodes:
            if origin == target:
                continue
            try:
                entry = matrix[origin][target]
            except KeyError:
                raise ValueError(f"matrix has no entry for {origin} -> {target}") from None
            graph.add_edge(origin, target, **_edge_attrs(entry, cost_per_km))
    return graph


def edge_weight(edge_data: Mapping, weights: Mapping[str, float] = config.EDGE_WEIGHTS) -> float:
    """One number for an edge: w_time x (minutes / time scale) + w_cost x (LKR / cost scale).

    The scales make minutes and rupees comparable before weighting.
    Usable directly in NetworkX, e.g. weight=lambda u, v, d: edge_weight(d, w).
    """
    if weights["time"] < 0 or weights["cost"] < 0:
        raise ValueError("edge weights must be >= 0")
    time_part = edge_data["duration_min"] / config.EDGE_TIME_SCALE_MIN
    cost_part = edge_data["cost_lkr"] / config.EDGE_COST_SCALE_LKR
    return weights["time"] * time_part + weights["cost"] * cost_part
