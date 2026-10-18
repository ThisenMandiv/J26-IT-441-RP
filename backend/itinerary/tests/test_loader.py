"""Tests for src/loader.py and the TripRequest model."""

import json

import pytest
from pydantic import ValidationError

from src import config
from src.loader import DestinationValidationError, load_destinations
from src.models import TripRequest


def valid_record(**overrides) -> dict:
    """A known-good destination record; override fields to break one rule at a time."""
    record = {
        "id": "T01",
        "name": "Test Place",
        "lat": 7.29,
        "lng": 80.64,
        "category": "heritage",
        "cost_lkr": 1000,
        "visit_duration_min": 60,
        "opening_time": "08:00",
        "closing_time": "17:00",
        "score": 0.5,
    }
    record.update(overrides)
    return record


@pytest.fixture
def write_json(tmp_path):
    """Write records to a temp JSON file and return its path."""
    def _write(records):
        path = tmp_path / "destinations.json"
        path.write_text(json.dumps(records), encoding="utf-8")
        return path
    return _write


# ---------- Valid data ----------

def test_mock_data_file_loads():
    destinations = load_destinations(config.DESTINATIONS_FILE)
    assert len(destinations) == 15
    assert len({d.id for d in destinations}) == 15


def test_valid_record_loads(write_json):
    destinations = load_destinations(write_json([valid_record()]))
    assert destinations[0].name == "Test Place"
    assert destinations[0].opening_time.hour == 8


def test_zero_cost_is_allowed(write_json):
    assert load_destinations(write_json([valid_record(cost_lkr=0)]))[0].cost_lkr == 0


# ---------- Validation rules ----------

@pytest.mark.parametrize("lat, lng", [
    (51.5, -0.12),   # London
    (5.0, 80.5),     # south of the island
    (7.5, 82.5),     # east, in the sea
])
def test_coordinates_outside_sri_lanka(write_json, lat, lng):
    with pytest.raises(DestinationValidationError, match="outside Sri Lanka"):
        load_destinations(write_json([valid_record(lat=lat, lng=lng)]))


@pytest.mark.parametrize("minutes", [0, -30])
def test_visit_duration_must_be_positive(write_json, minutes):
    with pytest.raises(DestinationValidationError, match="visit_duration_min"):
        load_destinations(write_json([valid_record(visit_duration_min=minutes)]))


@pytest.mark.parametrize("closing", ["08:00", "07:00"])
def test_closing_must_be_after_opening(write_json, closing):
    with pytest.raises(DestinationValidationError, match="closing_time"):
        load_destinations(write_json([valid_record(closing_time=closing)]))


def test_negative_cost(write_json):
    with pytest.raises(DestinationValidationError, match="cost_lkr"):
        load_destinations(write_json([valid_record(cost_lkr=-1)]))


def test_duplicate_ids(write_json):
    records = [valid_record(), valid_record(name="Other Place")]
    with pytest.raises(DestinationValidationError, match="duplicate id 'T01'"):
        load_destinations(write_json(records))


def test_missing_field_is_reported(write_json):
    record = valid_record()
    del record["lat"]
    with pytest.raises(DestinationValidationError, match="lat"):
        load_destinations(write_json([record]))


def test_error_names_the_bad_record(write_json):
    records = [valid_record(), valid_record(id="T02", name="Broken Place", cost_lkr=-5)]
    with pytest.raises(DestinationValidationError) as exc:
        load_destinations(write_json(records))
    message = str(exc.value)
    assert "record #1" in message
    assert "T02" in message
    assert "Broken Place" in message


def test_file_must_be_a_list(write_json):
    with pytest.raises(DestinationValidationError, match="JSON list"):
        load_destinations(write_json(valid_record()))


# ---------- TripRequest ----------

def test_trip_request_valid():
    req = TripRequest(num_days=3, total_budget_lkr=50000, start_lat=6.93, start_lng=79.85)
    assert req.day_start == config.DEFAULT_DAY_START


def test_trip_request_start_outside_sri_lanka():
    with pytest.raises(ValidationError, match="inside Sri Lanka"):
        TripRequest(num_days=3, total_budget_lkr=50000, start_lat=0, start_lng=0)


def test_trip_request_day_end_before_start():
    with pytest.raises(ValidationError, match="day_end"):
        TripRequest(num_days=1, total_budget_lkr=1000, start_lat=6.93, start_lng=79.85,
                    day_start="18:00", day_end="08:00")


def test_trip_request_zero_days():
    with pytest.raises(ValidationError):
        TripRequest(num_days=0, total_budget_lkr=1000, start_lat=6.93, start_lng=79.85)
