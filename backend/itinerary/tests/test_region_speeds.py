"""Tests for regional road speeds (config.USE_REGION_SPEEDS) in the haversine matrix."""

import pytest

from src import config
from src.distance import _fake_tag, _google_entry, build_fake_matrix, get_matrix, haversine_km, road_speed_kmh
from src.loader import load_destinations
from src.models import Location, TripRequest
from src.pipeline import run_sequential

# APPROX town coordinates. Kandy and Nuwara Eliya are inside the hill-country box.
KANDY = Location(id="KANDY", lat=7.2906, lng=80.6337)
NUWARA = Location(id="NUWARA", lat=6.9497, lng=80.7891)
COLOMBO = Location(id="COLOMBO", lat=6.9344, lng=79.8428)
GALLE = Location(id="GALLE", lat=6.0535, lng=80.2210)
HILL_SPEED = config.ROAD_SPEED_REGIONS[0][-1]


@pytest.fixture
def regions_on(monkeypatch):
    monkeypatch.setattr(config, "USE_REGION_SPEEDS", True)


def _speed(matrix, a, b):
    e = matrix[a.id][b.id]
    return e["distance_km"] / (e["duration_min"] / 60)


def test_region_lookup_and_fallback():
    assert road_speed_kmh(KANDY) == road_speed_kmh(NUWARA) == HILL_SPEED
    assert road_speed_kmh(COLOMBO) == road_speed_kmh(GALLE) == config.AVG_ROAD_SPEED_KMH
    assert road_speed_kmh(GALLE, fallback_kmh=55.0) == 55.0


def test_flag_off_matrix_is_the_old_single_speed():
    m = build_fake_matrix([KANDY, NUWARA, COLOMBO, GALLE])
    for a, b in ((KANDY, NUWARA), (COLOMBO, GALLE), (COLOMBO, KANDY)):
        assert _speed(m, a, b) == pytest.approx(config.AVG_ROAD_SPEED_KMH, rel=1e-3)


def test_hill_legs_are_slower_than_coast_legs(regions_on):
    m = build_fake_matrix([KANDY, NUWARA, COLOMBO, GALLE])
    assert _speed(m, KANDY, NUWARA) == pytest.approx(HILL_SPEED, rel=1e-3)
    assert _speed(m, COLOMBO, GALLE) == pytest.approx(config.AVG_ROAD_SPEED_KMH, rel=1e-3)
    mixed = _speed(m, COLOMBO, KANDY)  # half the road in each region
    assert HILL_SPEED < mixed < config.AVG_ROAD_SPEED_KMH
    assert m[COLOMBO.id][KANDY.id]["duration_min"] == pytest.approx(m[KANDY.id][COLOMBO.id]["duration_min"])


def test_distance_is_unchanged_only_time_changes(regions_on, monkeypatch):
    on = build_fake_matrix([KANDY, NUWARA])
    monkeypatch.setattr(config, "USE_REGION_SPEEDS", False)
    off = build_fake_matrix([KANDY, NUWARA])
    assert on[KANDY.id][NUWARA.id]["distance_km"] == off[KANDY.id][NUWARA.id]["distance_km"]
    assert on[KANDY.id][NUWARA.id]["duration_min"] > off[KANDY.id][NUWARA.id]["duration_min"]


def test_cache_tag_changes_only_when_the_flag_is_on(regions_on, monkeypatch, tmp_path):
    on_tag = _fake_tag()
    on = get_matrix([KANDY, NUWARA], cache_dir=tmp_path)
    monkeypatch.setattr(config, "USE_REGION_SPEEDS", False)
    assert _fake_tag() == f"haversine-speed{config.AVG_ROAD_SPEED_KMH}-factor{config.ROAD_DISTANCE_FACTOR}"
    assert on_tag != _fake_tag()
    off = get_matrix([KANDY, NUWARA], cache_dir=tmp_path)  # must not reuse the slower cached file
    assert off[KANDY.id][NUWARA.id]["duration_min"] < on[KANDY.id][NUWARA.id]["duration_min"]
    assert len(list(tmp_path.glob("*.json"))) == 2


def test_google_fallback_uses_region_speeds(regions_on):
    entry = _google_entry(KANDY, NUWARA, {"status": "ZERO_RESULTS"})
    km = haversine_km(KANDY.lat, KANDY.lng, NUWARA.lat, NUWARA.lng) * config.ROAD_DISTANCE_FACTOR
    assert entry["duration_min"] == pytest.approx(km / HILL_SPEED * 60, abs=0.01)
    # a real Google element is used as it is
    real = _google_entry(KANDY, NUWARA, {"status": "OK", "distance": {"value": 70_000}, "duration": {"value": 7200}})
    assert real["duration_min"] == 120.0


def test_hill_trip_takes_longer_with_the_flag(regions_on, monkeypatch, tmp_path):
    places = [p for p in load_destinations(config.DESTINATIONS_FILE) if p.id in {"D02", "D04", "D05", "D06", "D13"}]
    trip = TripRequest(num_days=2, total_budget_lkr=120_000, start_lat=KANDY.lat, start_lng=KANDY.lng)
    on = run_sequential(places, trip, cache_dir=tmp_path)
    monkeypatch.setattr(config, "USE_REGION_SPEEDS", False)
    off = run_sequential(places, trip, cache_dir=tmp_path)
    per_place = [r.score.breakdown["travel_min"] / max(1, sum(len(d.stops) for d in r.itinerary.days))
                 for r in (on, off)]
    assert per_place[0] > per_place[1]
