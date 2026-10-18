"""Tests for src/distance.py. No network calls: Google is never contacted."""

import pytest

from src import config, distance
from src.distance import (
    MissingApiKeyError,
    build_fake_matrix,
    get_google_matrix,
    get_matrix,
    get_matrix_with_start,
    haversine_km,
)
from src.loader import load_destinations
from src.models import TripRequest


@pytest.fixture
def destinations():
    return load_destinations(config.DESTINATIONS_FILE)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Safety net: fail loudly if any test tries to reach Google."""
    def _blocked(*args, **kwargs):
        raise AssertionError("network call attempted in tests")
    monkeypatch.setattr(distance, "_fetch_batch", _blocked)


# ---------- haversine_km ----------

def test_haversine_same_point_is_zero():
    assert haversine_km(7.0, 80.0, 7.0, 80.0) == 0.0


def test_haversine_one_degree_of_longitude_at_equator():
    # 2 * pi * 6371 / 360 = 111.19 km
    assert haversine_km(0, 0, 0, 1) == pytest.approx(111.19, abs=0.01)


# ---------- build_fake_matrix ----------

def test_distance_to_itself_is_zero(destinations):
    matrix = build_fake_matrix(destinations)
    for d in destinations:
        assert matrix[d.id][d.id]["distance_km"] == 0
        assert matrix[d.id][d.id]["duration_min"] == 0


def test_fake_matrix_is_symmetric(destinations):
    matrix = build_fake_matrix(destinations)
    for a in destinations:
        for b in destinations:
            assert matrix[a.id][b.id] == matrix[b.id][a.id]


def test_entry_for_every_ordered_pair(destinations):
    matrix = build_fake_matrix(destinations)
    ids = {d.id for d in destinations}
    assert set(matrix) == ids
    for origin_id in ids:
        assert set(matrix[origin_id]) == ids
    assert sum(len(row) for row in matrix.values()) == len(ids) ** 2


def test_road_factor_and_speed_are_applied(destinations):
    a, b = destinations[0], destinations[1]
    matrix = build_fake_matrix(destinations, avg_speed_kmh=50, road_factor=1.5)
    expected_km = haversine_km(a.lat, a.lng, b.lat, b.lng) * 1.5
    assert matrix[a.id][b.id]["distance_km"] == pytest.approx(expected_km, abs=0.001)
    assert matrix[a.id][b.id]["duration_min"] == pytest.approx(expected_km / 50 * 60, abs=0.01)
    assert matrix[a.id][b.id]["source"] == "haversine"


def test_zero_speed_rejected(destinations):
    with pytest.raises(ValueError):
        build_fake_matrix(destinations, avg_speed_kmh=0)


# ---------- Cache ----------

def test_cache_is_written_then_reused(destinations, tmp_path, monkeypatch):
    first = get_matrix(destinations, cache_dir=tmp_path)
    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1

    # If the cache is reused, the matrix is never rebuilt.
    def _must_not_run(*args, **kwargs):
        raise AssertionError("matrix rebuilt instead of read from cache")
    monkeypatch.setattr(distance, "build_fake_matrix", _must_not_run)

    second = get_matrix(destinations, cache_dir=tmp_path)
    assert second == first
    assert list(tmp_path.glob("*.json")) == files


def test_cache_key_ignores_order(destinations, tmp_path):
    get_matrix(destinations, cache_dir=tmp_path)
    get_matrix(list(reversed(destinations)), cache_dir=tmp_path)
    assert len(list(tmp_path.glob("*.json"))) == 1


def test_different_set_gets_its_own_cache_file(destinations, tmp_path):
    get_matrix(destinations, cache_dir=tmp_path)
    get_matrix(destinations[:5], cache_dir=tmp_path)
    assert len(list(tmp_path.glob("*.json"))) == 2


# ---------- Google client (offline: the HTTP call is replaced) ----------

def test_google_requires_api_key(destinations, tmp_path, monkeypatch):
    monkeypatch.delenv(config.GOOGLE_API_KEY_ENV, raising=False)
    monkeypatch.setattr(distance, "load_dotenv", lambda *a, **k: None)  # ignore a real .env
    with pytest.raises(MissingApiKeyError):
        get_matrix(destinations, use_google=True, cache_dir=tmp_path)


def test_google_batches_respect_limit_and_match_structure(destinations, monkeypatch):
    calls = []

    def fake_fetch(origins, targets, api_key):
        calls.append((len(origins), len(targets)))
        element = {"status": "OK", "distance": {"value": 12000}, "duration": {"value": 1800}}
        return {"status": "OK", "rows": [{"elements": [element] * len(targets)} for _ in origins]}

    monkeypatch.setattr(distance, "_fetch_batch", fake_fetch)
    matrix = get_google_matrix(destinations, api_key="test-key")

    assert len(calls) == 4  # 15 places -> blocks of 10 + 5, so 2 x 2 requests
    assert all(o * t <= 100 for o, t in calls)
    assert {k: set(v) for k, v in matrix.items()} == {
        k: set(v) for k, v in build_fake_matrix(destinations).items()
    }
    a, b = destinations[0].id, destinations[1].id
    assert matrix[a][b] == {"distance_km": 12.0, "duration_min": 30.0, "source": "google"}
    assert matrix[a][a]["distance_km"] == 0


def test_google_missing_route_falls_back_to_estimate(destinations, monkeypatch):
    def fake_fetch(origins, targets, api_key):
        element = {"status": "ZERO_RESULTS"}
        return {"status": "OK", "rows": [{"elements": [element] * len(targets)} for _ in origins]}

    monkeypatch.setattr(distance, "_fetch_batch", fake_fetch)
    matrix = get_google_matrix(destinations[:3], api_key="test-key")
    a, b = destinations[0].id, destinations[1].id
    assert matrix[a][b]["source"] == "haversine"
    assert matrix[a][b]["distance_km"] > 0


# ---------- Start point ----------

def _trip(lat: float, lng: float) -> TripRequest:
    return TripRequest(num_days=2, total_budget_lkr=50_000, start_lat=lat, start_lng=lng)


def test_matrix_with_start_adds_start_row_and_column(destinations, tmp_path):
    matrix = get_matrix_with_start(destinations, _trip(6.9344, 79.8428), cache_dir=tmp_path)
    start = config.START_NODE_ID
    assert set(matrix) == {start} | {d.id for d in destinations}
    assert matrix[start][start]["distance_km"] == 0
    assert all(matrix[start][d.id]["distance_km"] > 0 for d in destinations)
    assert all(d.id in matrix and start in matrix[d.id] for d in destinations)


def test_different_start_points_get_their_own_cache_file(destinations, tmp_path):
    a = get_matrix_with_start(destinations, _trip(6.9344, 79.8428), cache_dir=tmp_path)  # Colombo
    b = get_matrix_with_start(destinations, _trip(7.2906, 80.6337), cache_dir=tmp_path)  # Kandy
    assert len(list(tmp_path.glob("*.json"))) == 2
    first = destinations[0].id
    assert a[config.START_NODE_ID][first] != b[config.START_NODE_ID][first]


def test_destination_named_start_is_rejected(destinations, tmp_path):
    clash = destinations[0].model_copy(update={"id": config.START_NODE_ID})
    with pytest.raises(ValueError, match="reserved"):
        get_matrix_with_start([clash], _trip(6.9344, 79.8428), cache_dir=tmp_path)
