"""Shortest paths on the travel graph: Dijkstra and A* (WBS 3.4).

Both are my own heapq implementations sharing one search loop (_search).
Edge cost = graph.edge_weight(edge_data, weights), so they optimise the same
time + cost weight that the rest of the pipeline uses.

"Nodes expanded" = nodes taken off the heap and settled (the target included).
It is the usual measure of how much work a search does.

Run `python -m src.routing` to compare both algorithms on the 15-place mock graph.
"""

import heapq
import itertools
import math
import time
from collections.abc import Callable, Hashable, Mapping
from typing import NamedTuple

import networkx as nx

from src import config
from src.distance import haversine_km
from src.graph import edge_weight
from src import transport

Weights = Mapping[str, float]
Heuristic = Callable[[Hashable], float]


class NoPathError(ValueError):
    """Raised when the target cannot be reached from the source."""


class RouteResult(NamedTuple):
    path: list[Hashable]
    total_weight: float
    nodes_expanded: int


# ---------- Shared search loop ----------

def _zero_heuristic(node: Hashable) -> float:
    return 0.0


def _search(
    graph: nx.DiGraph,
    source: Hashable,
    target: Hashable | None,
    weights: Weights,
    heuristic: Heuristic = _zero_heuristic,
) -> tuple[dict, dict, int]:
    """Best-first search ordered by g + h. With h = 0 this is Dijkstra.

    Stops when the target is settled; with target=None it settles every reachable node.
    Returns (distance to each reached node, parent of each node, nodes expanded).
    Settled nodes are never reopened, which is correct because h is consistent
    (never drops by more than the edge weight along any edge).
    """
    dist = {source: 0.0}
    parent: dict[Hashable, Hashable | None] = {source: None}
    settled: set[Hashable] = set()
    tie = itertools.count()  # breaks ties so the heap never compares node ids
    heap = [(heuristic(source), next(tie), source)]

    while heap:
        _, _, node = heapq.heappop(heap)
        if node in settled:
            continue  # stale entry: a shorter route was already found
        settled.add(node)
        if node == target:
            break
        for neighbour, data in graph[node].items():
            if neighbour in settled:
                continue
            new_dist = dist[node] + edge_weight(data, weights)
            if new_dist < dist.get(neighbour, math.inf):
                dist[neighbour] = new_dist
                parent[neighbour] = node
                heapq.heappush(heap, (new_dist + heuristic(neighbour), next(tie), neighbour))
    return dist, parent, len(settled)


def _check_nodes(graph: nx.DiGraph, *nodes: Hashable) -> None:
    for node in nodes:
        if node not in graph:
            raise KeyError(f"node {node!r} is not in the graph")


def _build_path(parent: dict, target: Hashable) -> list[Hashable]:
    """Walk parent links back from the target, then reverse."""
    path = [target]
    while parent[path[-1]] is not None:
        path.append(parent[path[-1]])
    return path[::-1]


def _route(graph, source, target, weights, heuristic) -> RouteResult:
    _check_nodes(graph, source, target)
    dist, parent, expanded = _search(graph, source, target, weights, heuristic)
    if target not in dist:
        raise NoPathError(f"no path from {source!r} to {target!r}")
    return RouteResult(_build_path(parent, target), dist[target], expanded)


# ---------- Dijkstra ----------

def dijkstra(
    graph: nx.DiGraph,
    source: Hashable,
    target: Hashable,
    weights: Weights = config.EDGE_WEIGHTS,
) -> RouteResult:
    """Lowest-weight path from source to target (explores in order of distance so far)."""
    return _route(graph, source, target, weights, _zero_heuristic)


# ---------- A* ----------

def haversine_heuristic(
    graph: nx.DiGraph,
    target: Hashable,
    weights: Weights = config.EDGE_WEIGHTS,
    max_speed_kmh: float = config.MAX_PLAUSIBLE_SPEED_KMH,
    min_cost_per_km: float | None = None,
) -> Heuristic:
    """Lower bound on the weight left from a node to the target.

    No road is shorter than the straight line, no leg is faster than max_speed_kmh
    and no km is cheaper than min_cost_per_km, so this best-case "edge" can only
    be cheaper than the real route: the heuristic never overestimates.
    It goes through edge_weight() so it is in exactly the same units.
    min_cost_per_km=None: the cheapest rate in use right now (car only, or the cheapest
    transport mode when config.USE_TRANSPORT_MODES is on), see transport.min_cost_per_km.
    """
    min_cost_per_km = transport.min_cost_per_km() if min_cost_per_km is None else min_cost_per_km
    goal = graph.nodes[target]

    def h(node: Hashable) -> float:
        here = graph.nodes[node]
        km = haversine_km(here["lat"], here["lng"], goal["lat"], goal["lng"])
        best_case = {"duration_min": km / max_speed_kmh * 60, "cost_lkr": km * min_cost_per_km}
        return edge_weight(best_case, weights)

    return h


def astar(
    graph: nx.DiGraph,
    source: Hashable,
    target: Hashable,
    weights: Weights = config.EDGE_WEIGHTS,
) -> RouteResult:
    """Lowest-weight path, guided towards the target by the haversine heuristic."""
    _check_nodes(graph, source, target)
    return _route(graph, source, target, weights, haversine_heuristic(graph, target, weights))


# ---------- All pairs (input for TSP, WBS 3.5) ----------

def shortest_path_matrix(graph: nx.DiGraph, weights: Weights = config.EDGE_WEIGHTS) -> dict:
    """Shortest-path weight and path for every ordered pair of nodes.

    result[u][v] = {"weight": float, "path": [u, ..., v]}
    Unreachable pairs get weight inf and an empty path.
    Runs one full Dijkstra per source node (n runs instead of n x n).
    """
    result = {}
    for source in graph.nodes:
        dist, parent, _ = _search(graph, source, None, weights)
        result[source] = {
            target: {"weight": dist[target], "path": _build_path(parent, target)}
            if target in dist else {"weight": math.inf, "path": []}
            for target in graph.nodes
        }
    return result


# ---------- Benchmark ----------

def compare_algorithms(graph: nx.DiGraph, weights: Weights = config.EDGE_WEIGHTS) -> dict:
    """Run Dijkstra and A* on every ordered pair; print total nodes expanded and run time."""
    pairs = [(u, v) for u in graph.nodes for v in graph.nodes if u != v]
    totals = {}
    for name, algorithm in (("Dijkstra", dijkstra), ("A*", astar)):
        expanded = 0
        start = time.perf_counter()
        for u, v in pairs:
            expanded += algorithm(graph, u, v, weights).nodes_expanded
        totals[name] = {"nodes_expanded": expanded, "seconds": time.perf_counter() - start}

    print(f"{len(pairs)} source-target pairs on {graph.number_of_nodes()} nodes")
    print(f"{'algorithm':<10}{'nodes expanded':>16}{'avg per query':>15}{'run time (ms)':>15}")
    for name, t in totals.items():
        print(f"{name:<10}{t['nodes_expanded']:>16}{t['nodes_expanded'] / len(pairs):>15.2f}"
              f"{t['seconds'] * 1000:>15.2f}")
    return totals


if __name__ == "__main__":
    from src.distance import get_matrix_with_start
    from src.graph import build_graph
    from src.loader import load_destinations
    from src.models import TripRequest

    destinations = load_destinations(config.DESTINATIONS_FILE)
    trip = TripRequest(num_days=3, total_budget_lkr=100_000, start_lat=6.9344, start_lng=79.8428)
    graph = build_graph(destinations, get_matrix_with_start(destinations, trip), trip)
    compare_algorithms(graph)
