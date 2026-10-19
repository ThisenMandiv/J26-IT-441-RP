"""Tests for transport modes per leg (src/transport.py) and their use in graph, A* and pipelines."""

import itertools

import pytest

from src import config, transport
from src.distance import get_matrix_with_start, haversine_km
from src.graph import build_graph, edge_weight
from src.loader import load_destinations
from src.models import TripRequest
from src.pipeline import run_naive, run_sequential
from src.routing import astar, dijkstra, haversine_heuristic
from src.transport import ModeOption, choose_mode, leg_value, mode_options

W = config.EVALUATION_WEIGHT_SETTINGS
TRIP = TripRequest(num_days=3, total_budget_lkr=100_000, start_lat=6.9344, start_lng=79.8428)


@pytest.fixture
def modes_on(monkeypatch):
    monkeypatch.setattr(config, "USE_TRANSPORT_MODES", True)


@pytest.fixture(scope="module")
def places():
    return load_destinations(config.DESTINATIONS_FILE)


@pytest.fixture
def matrix(places, tmp_path):
    return get_matrix_with_start(places, TRIP, cache_dir=tmp_path)


# ---------- Options and choice ----------

def test_car_option_is_exactly_the_old_driving_estimate():
    car = next(o for o in mode_options(52.0, 78.0) if o.mode == "car")
    assert car == ModeOption("car", 78.0, 52.0 * config.TRAVEL_COST_PER_KM_LKR)


def test_bus_is_slower_and_cheaper_and_walk_only_for_short_legs():
    long_leg = {o.mode: o for o in mode_options(52.0, 78.0)}
    assert set(long_leg) == {"car", "bus"}  # 52 km is too far to walk
    bus = config.TRANSPORT_MODES["bus"]
    assert long_leg["bus"].duration_min == pytest.approx(
        78.0 * config.AVG_ROAD_SPEED_KMH / bus["speed_kmh"] + bus["wait_min"], abs=0.01)
    assert long_leg["bus"].cost_lkr < long_leg["car"].cost_lkr
    assert {o.mode for o in mode_options(1.0, 1.5)} == {"car", "bus", "walk"}


def test_leg_value_uses_the_objective_scales():
    option = ModeOption("car", 60.0, 10_000.0)  # one hour and 10,000 LKR
    assert leg_value(option, {"travel_time": 2.0, "spend": 3.0}) == pytest.approx(5.0)


def test_time_traveller_drives_budget_traveller_takes_the_bus_on_long_legs():
    km, minutes = 100.0, 150.0  # a long leg at the 40 km/h average
    assert choose_mode(km, minutes, W["time"]).mode == "car"
    assert choose_mode(km, minutes, W["default"]).mode == "car"
    assert choose_mode(km, minutes, W["budget"]).mode == "bus"


def test_budget_traveller_drives_when_the_bus_is_much_slower(monkeypatch):
    monkeypatch.setitem(config.TRANSPORT_MODES, "bus", {**config.TRANSPORT_MODES["bus"], "speed_kmh": 8.0})
    assert choose_mode(100.0, 150.0, W["budget"]).mode == "car"


def test_short_legs_stay_by_car_because_of_the_bus_wait():
    assert choose_mode(5.0, 7.5, W["budget"]).mode == "car"


def test_tie_goes_to_the_first_mode():
    free_time = {"travel_time": 0.0, "spend": 0.0}  # every option is worth 0
    assert choose_mode(50.0, 75.0, free_time).mode == "car"


def test_no_allowed_mode_raises(monkeypatch):
    monkeypatch.setattr(config, "TRANSPORT_MODES", {"walk": config.TRANSPORT_MODES["walk"]})
    with pytest.raises(ValueError, match="no transport mode"):
        choose_mode(50.0, 75.0, W["default"])


# ---------- Graph ----------

def test_flag_off_graph_has_no_modes_and_ignores_mode_weights(places, matrix):
    plain = build_graph(places, matrix, TRIP)
    with_weights = build_graph(places, matrix, TRIP, mode_weights=W["budget"])
    assert all("mode" not in d for _, _, d in plain.edges(data=True))
    assert list(plain.edges(data=True)) == list(with_weights.edges(data=True))


def test_flag_on_graph_picks_modes_by_weights(places, matrix, modes_on):
    def modes(weights):
        g = build_graph(places, matrix, TRIP, mode_weights=weights)
        return [d["mode"] for _, _, d in g.edges(data=True)]

    assert set(modes(W["time"])) == {"car"}
    assert modes(W["budget"]).count("bus") > modes(W["default"]).count("bus")
    assert "bus" in modes(W["budget"])


def test_flag_on_car_edges_keep_the_old_time_and_cost(places, matrix, modes_on):
    old = build_graph(places, matrix, TRIP, cost_per_km=config.TRAVEL_COST_PER_KM_LKR)
    new = build_graph(places, matrix, TRIP, mode_weights=W["time"])  # all car
    for u, v, d in new.edges(data=True):
        assert (d["duration_min"], d["cost_lkr"]) == (old.edges[u, v]["duration_min"], old.edges[u, v]["cost_lkr"])


# ---------- A* stays admissible ----------

def test_min_cost_per_km_follows_the_flag(monkeypatch):
    assert transport.min_cost_per_km() == config.MIN_TRAVEL_COST_PER_KM_LKR == config.TRAVEL_COST_PER_KM_LKR
    monkeypatch.setattr(config, "USE_TRANSPORT_MODES", True)
    cheapest = min(m["cost_per_km_lkr"] for m in config.TRANSPORT_MODES.values())
    assert transport.min_cost_per_km() == config.MIN_TRAVEL_COST_PER_KM_LKR_MODES == cheapest


@pytest.mark.parametrize("regions", [False, True])
@pytest.mark.parametrize("wname", list(W))
def test_heuristic_is_admissible_and_consistent_with_modes(places, modes_on, wname, regions, monkeypatch, tmp_path):
    """Every edge is at least as expensive as the straight-line best case (=> consistent),
    and A* finds the same lowest weight as Dijkstra for every pair. Also with hill speeds on."""
    monkeypatch.setattr(config, "USE_REGION_SPEEDS", regions)
    matrix = get_matrix_with_start(places, TRIP, cache_dir=tmp_path)
    graph = build_graph(places, matrix, TRIP, mode_weights=W[wname])
    for u, v, d in graph.edges(data=True):
        a, b = graph.nodes[u], graph.nodes[v]
        km = haversine_km(a["lat"], a["lng"], b["lat"], b["lng"])
        assert km / (d["duration_min"] / 60) <= config.MAX_PLAUSIBLE_SPEED_KMH
        assert d["cost_lkr"] >= km * transport.min_cost_per_km() - 1e-9
        best_case = {"duration_min": km / config.MAX_PLAUSIBLE_SPEED_KMH * 60,
                     "cost_lkr": km * transport.min_cost_per_km()}
        assert edge_weight(best_case) <= edge_weight(d) + 1e-9
    for u, v in itertools.permutations(list(graph.nodes)[:8], 2):
        h = haversine_heuristic(graph, v)
        exact = dijkstra(graph, u, v).total_weight
        assert h(u) <= exact + 1e-9
        assert astar(graph, u, v).total_weight == pytest.approx(exact)


def test_old_car_bound_would_overestimate_with_modes(places, matrix, modes_on):
    """Why the bound must follow the flag: the car rate is above a bus edge's cost per km."""
    graph = build_graph(places, matrix, TRIP, mode_weights=W["budget"])
    u, v, d = next((u, v, d) for u, v, d in graph.edges(data=True) if d["mode"] == "bus")
    a, b = graph.nodes[u], graph.nodes[v]
    km = haversine_km(a["lat"], a["lng"], b["lat"], b["lng"])
    assert d["cost_lkr"] < km * config.TRAVEL_COST_PER_KM_LKR


# ---------- Pipelines ----------

def test_sequential_and_naive_use_the_modes(places, tmp_path, modes_on):
    budget = run_sequential(places, TRIP, cache_dir=tmp_path, mode_weights=W["budget"])
    time_ = run_sequential(places, TRIP, cache_dir=tmp_path, mode_weights=W["time"])
    budget_modes = {s.travel_mode for d in budget.itinerary.days for s in d.stops}
    assert any("bus" in m for m in budget_modes)
    assert {s.travel_mode for d in time_.itinerary.days for s in d.stops} == {"car"}
    naive = run_naive(places, TRIP, cache_dir=tmp_path, mode_weights=W["budget"])
    assert all(s.travel_mode in {"car", "bus", "walk"} for d in naive.itinerary.days for s in d.stops)


def test_budget_traveller_pays_less_per_km_travelled(places, tmp_path, modes_on):
    def per_km(weights):
        r = run_sequential(places, TRIP, cache_dir=tmp_path, mode_weights=weights)
        stops = [s for d in r.itinerary.days for s in d.stops]
        g = r.graph
        km = sum(g.edges[a, b]["distance_km"] for a, b in
                 zip([config.START_NODE_ID] + [s.destination_id for s in stops], [s.destination_id for s in stops])
                 if (a, b) in g.edges)
        return sum(s.travel_cost_lkr for s in stops) / km

    assert per_km(W["budget"]) < per_km(W["time"])


def test_flag_off_stops_have_no_mode(places, tmp_path):
    r = run_sequential(places, TRIP, cache_dir=tmp_path, mode_weights=W["budget"])
    assert {s.travel_mode for d in r.itinerary.days for s in d.stops} == {None}
