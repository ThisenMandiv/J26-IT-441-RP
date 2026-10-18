"""Visit order for the destinations: TSP approximation (WBS 3.5).

The traveller leaves START and visits every stop once. The route is an *open*
path (no return to START), because day splitting in 3.6 decides where each day ends.

Costs come from routing.shortest_path_matrix(): cost_matrix[u][v]["weight"] is the
shortest-path weight from u to v (time + cost, see graph.edge_weight).
Costs may be asymmetric (Google times differ A->B vs B->A), so every function
uses the real direction of travel.

- nearest_neighbor_order: fast greedy guess
- two_opt:                improves a guess by reversing segments
- exact_best_order:       true optimum (Held-Karp DP), small sets only, for evaluation
"""

import math
from collections.abc import Hashable, Iterable, Sequence

from src import config

CostMatrix = dict[Hashable, dict[Hashable, dict]]

MAX_EXACT_STOPS = 10  # Held-Karp is O(n^2 x 2^n): about 100k steps at 10 stops
IMPROVEMENT_EPS = 1e-9  # ignore float noise so 2-opt cannot loop forever


def _cost(cost_matrix: CostMatrix, u: Hashable, v: Hashable) -> float:
    return cost_matrix[u][v]["weight"]


def _stops(cost_matrix: CostMatrix, start: Hashable, stops: Iterable | None) -> list:
    """Stops to visit: given list, or every node in the matrix except START."""
    if start not in cost_matrix:
        raise KeyError(f"start {start!r} is not in the cost matrix")
    stops = [n for n in cost_matrix if n != start] if stops is None else list(stops)
    if start in stops:
        raise ValueError("stops must not include the start node")
    if len(set(stops)) != len(stops):
        raise ValueError("stops must not contain duplicates")
    return stops


def route_cost(order: Sequence[Hashable], cost_matrix: CostMatrix) -> float:
    """Total weight of travelling the order leg by leg (inf if a leg is unreachable)."""
    return sum(_cost(cost_matrix, u, v) for u, v in zip(order, order[1:]))


# ---------- Nearest neighbour ----------

def nearest_neighbor_order(
    cost_matrix: CostMatrix,
    start: Hashable = config.START_NODE_ID,
    stops: Iterable | None = None,
) -> list[Hashable]:
    """Greedy: from the current place, always go to the cheapest unvisited stop next."""
    remaining = _stops(cost_matrix, start, stops)
    order = [start]
    while remaining:
        here = order[-1]
        nearest = min(remaining, key=lambda s: _cost(cost_matrix, here, s))  # ties: first in list
        order.append(nearest)
        remaining.remove(nearest)
    return order


# ---------- 2-opt ----------

def two_opt(order: Sequence[Hashable], cost_matrix: CostMatrix) -> tuple[list[Hashable], float]:
    """Reverse a segment order[i..j] whenever that lowers the cost; stop when no reversal helps.

    START (index 0) never moves. The full route cost is recomputed for each candidate,
    because with asymmetric costs reversing a segment changes the legs inside it too.
    Returns (improved order, its total cost).
    """
    best = list(order)
    best_cost = route_cost(best, cost_matrix)
    improved = True
    while improved:
        improved = False
        for i in range(1, len(best) - 1):
            for j in range(i + 1, len(best)):
                candidate = best[:i] + best[i:j + 1][::-1] + best[j + 1:]
                candidate_cost = route_cost(candidate, cost_matrix)
                if candidate_cost < best_cost - IMPROVEMENT_EPS:
                    best, best_cost = candidate, candidate_cost
                    improved = True
    return best, best_cost


# ---------- Exact (Held-Karp dynamic programming) ----------

def exact_best_order(
    cost_matrix: CostMatrix,
    start: Hashable = config.START_NODE_ID,
    stops: Iterable | None = None,
    max_stops: int = MAX_EXACT_STOPS,
) -> tuple[list[Hashable], float]:
    """Optimal open path from START through every stop, for small sets only.

    best[mask][j] = cheapest cost to leave START, visit exactly the stops in `mask`
    (a bitmask) and end at stop j. Each entry is built from smaller masks:
        best[mask][j] = min over k in mask-{j} of best[mask-{j}][k] + cost(k, j)
    Answer = min over j of best[all stops][j]. Returns (order, cost).
    """
    stops = _stops(cost_matrix, start, stops)
    n = len(stops)
    if n > max_stops:
        raise ValueError(f"exact solver allows at most {max_stops} stops, got {n}")
    if n == 0:
        return [start], 0.0

    full = (1 << n) - 1
    best = [[math.inf] * n for _ in range(full + 1)]
    parent = [[-1] * n for _ in range(full + 1)]
    for j in range(n):
        best[1 << j][j] = _cost(cost_matrix, start, stops[j])

    for mask in range(1, full + 1):
        for j in range(n):
            if not mask & (1 << j) or mask == 1 << j:
                continue  # j must be in the set, and singletons are already set
            prev_mask = mask ^ (1 << j)
            for k in range(n):
                if prev_mask & (1 << k):
                    cost = best[prev_mask][k] + _cost(cost_matrix, stops[k], stops[j])
                    if cost < best[mask][j]:
                        best[mask][j], parent[mask][j] = cost, k

    last = min(range(n), key=lambda j: best[full][j])
    total = best[full][last]

    # Walk the parent table back from the last stop.
    order, mask, j = [], full, last
    while j != -1:
        order.append(stops[j])
        mask, j = mask ^ (1 << j), parent[mask][j]
    return [start, *order[::-1]], total


# ---------- Comparison ----------

def compare_orders(
    cost_matrix: CostMatrix,
    start: Hashable = config.START_NODE_ID,
    stops: Iterable | None = None,
) -> dict:
    """Print nearest neighbour, 2-opt and exact costs, and each one's gap to the optimum."""
    stops = _stops(cost_matrix, start, stops)
    nn = nearest_neighbor_order(cost_matrix, start, stops)
    nn_cost = route_cost(nn, cost_matrix)
    opt2, opt2_cost = two_opt(nn, cost_matrix)
    exact, exact_cost = exact_best_order(cost_matrix, start, stops)

    results = {
        "nearest_neighbor": {"order": nn, "cost": nn_cost},
        "two_opt": {"order": opt2, "cost": opt2_cost},
        "exact": {"order": exact, "cost": exact_cost},
    }
    print(f"{len(stops)} stops from {start}")
    print(f"{'method':<18}{'cost':>10}{'gap to exact':>14}  order")
    for name, r in results.items():
        gap = (r["cost"] - exact_cost) / exact_cost * 100 if exact_cost else 0.0
        print(f"{name:<18}{r['cost']:>10.3f}{gap:>13.2f}%  {' > '.join(map(str, r['order']))}")
    return results


if __name__ == "__main__":
    from src.distance import get_matrix_with_start
    from src.graph import build_graph
    from src.loader import load_destinations
    from src.models import TripRequest
    from src.routing import shortest_path_matrix

    # 8 highest-scored mock destinations, as Component 1 would rank them.
    destinations = load_destinations(config.DESTINATIONS_FILE)
    top8 = sorted(destinations, key=lambda d: d.score, reverse=True)[:8]
    trip = TripRequest(num_days=3, total_budget_lkr=100_000, start_lat=6.9344, start_lng=79.8428)
    graph = build_graph(top8, get_matrix_with_start(top8, trip), trip)
    compare_orders(shortest_path_matrix(graph))
