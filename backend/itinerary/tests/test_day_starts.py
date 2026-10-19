"""Tests for per-day start times (TripRequest.day_starts) and evening drives."""

from datetime import time

import pytest
from pydantic import ValidationError

from src import config
from src.distance import build_fake_matrix, start_location
from src.exact import exact_benchmark
from src.graph import build_graph
from src.joint import optimize_joint
from src.models import Destination, TripRequest
from src.pipeline import run_naive, run_sequential
from src.scenarios import build_scenarios
from src.scheduler import Leg, _try_stop, attempt, day_window, schedule_days, schedule_fixed, to_minutes

START = config.START_NODE_ID
COLOMBO = (6.9344, 79.8428)


def trip(num_days=2, **kwargs) -> TripRequest:
    return TripRequest(num_days=num_days, total_budget_lkr=200_000, start_lat=COLOMBO[0],
                       start_lng=COLOMBO[1], **kwargs)


def place(id, opening, closing, visit, km_north=2.0) -> Destination:
    """Invented test place km_north of Colombo (130 km of road = 195 min at 40 km/h)."""
    return Destination(id=id, name=f"Place {id}", lat=COLOMBO[0] + km_north / 111, lng=COLOMBO[1],
                       category="test", cost_lkr=500.0, visit_duration_min=visit,
                       opening_time=opening, closing_time=closing, score=0.8)


HIKE = place("HIKE", time(5, 30), time(12, 0), 300)  # 5 hours, must start early
NEAR = place("NEAR", time(6, 0), time(22, 0), 60)
FAR = place("FAR", time(6, 0), time(11, 0), 60, km_north=100.0)  # about 3 h away, closes 11:00


def schedule(places, t):
    g = build_graph(places, build_fake_matrix([start_location(t), *places]), t)
    return schedule_days([START, *(p.id for p in places)], g, t), g


def all_ids(days):
    return [s.destination_id for d in days for s in d.stops]


# ---------- TripRequest ----------

def test_defaults_are_the_old_behaviour():
    t = trip(3)
    assert t.day_starts is None and t.evening_drive_limit_min is None
    assert [t.start_of_day(d) for d in (1, 2, 3)] == [t.day_start] * 3
    assert t.evening_limit_min() == 0


def test_evening_limit_comes_from_the_flag_unless_set(monkeypatch):
    assert trip(evening_drive_limit_min=90).evening_limit_min() == 90  # explicit request wins
    monkeypatch.setattr(config, "USE_EVENING_DRIVE", True)
    assert trip().evening_limit_min() == config.EVENING_DRIVE_LIMIT_MIN
    assert trip(evening_drive_limit_min=0).evening_limit_min() == 0


def test_day_starts_validation():
    t = trip(2, day_starts=[time(8, 0), time(5, 30)])
    assert t.start_of_day(2) == time(5, 30)
    with pytest.raises(ValidationError, match="one time per day"):
        trip(2, day_starts=[time(8, 0)])
    with pytest.raises(ValidationError, match="before day_end"):
        trip(2, day_starts=[time(8, 0), time(19, 0)])
    with pytest.raises(ValidationError):
        trip(evening_drive_limit_min=-5)


# ---------- day_window and attempt ----------

def test_day_window():
    assert day_window(trip(), 1, None) == (8 * 60, 18 * 60, -1)
    assert day_window(trip(), 2, 15 * 60) == (8 * 60, 18 * 60, -1)  # no evening drives by default
    t = trip(day_starts=[time(8, 0), time(5, 30)], evening_drive_limit_min=120)
    assert day_window(t, 1, None).evening_min == -1  # nothing before day 1
    assert day_window(t, 2, 15 * 60) == (5 * 60 + 30, 18 * 60, 18 * 60 + 120 - 15 * 60)


def test_evening_drive_is_only_a_fallback():
    far = {"opening_time": time(6, 0), "closing_time": time(11, 0), "visit_duration_min": 60}
    leg = Leg(200, 1000.0)
    morning = attempt(far, leg, 8 * 60, 18 * 60, 60)
    assert not morning.ok and morning == _try_stop(far, leg, 8 * 60, 18 * 60, 60)
    assert attempt(far, leg, 8 * 60, 18 * 60, 60, evening_min=199) == morning  # drive too long
    r = attempt(far, leg, 8 * 60, 18 * 60, 60, evening_min=200)
    assert r.ok and r.evening and r.arrival == 8 * 60 and r.leg == leg  # travel still counted
    near = {**far, "closing_time": time(22, 0)}
    assert not attempt(near, leg, 8 * 60, 18 * 60, 60, evening_min=500).evening  # morning works


# ---------- Whole schedules ----------

def test_early_start_day_makes_the_hike_possible():
    off, _ = schedule([HIKE], trip())
    assert all_ids(off.days) == [] and "open only 240 min" in off.unscheduled[0].reason
    on, _ = schedule([HIKE], trip(day_starts=[time(8, 0), time(5, 30)]))
    assert [len(d.stops) for d in on.days] == [0, 1]
    assert on.days[1].stops[0].arrival_time >= time(5, 30)


def test_evening_drive_reaches_a_place_that_closes_before_noon():
    off, _ = schedule([NEAR, FAR], trip())
    assert all_ids(off.days) == ["NEAR"]
    on, g = schedule([NEAR, FAR], trip(evening_drive_limit_min=120))
    assert all_ids(on.days) == ["NEAR", "FAR"]
    far_stop = on.days[1].stops[0]
    assert far_stop.evening_drive and far_stop.arrival_time == time(8, 0)
    assert far_stop.travel_time_min > 180  # the drive is still in the plan's travel time


def test_evening_drive_respects_the_limit():
    # NEAR takes until 17:00, so the 3-hour drive would end after 18:00 + 60 min
    late = place("NEAR", time(6, 0), time(22, 0), 9 * 60 - 4)
    on, _ = schedule([late, FAR], trip(evening_drive_limit_min=60))
    assert all_ids(on.days) == ["NEAR"]
    on, _ = schedule([late, FAR], trip(evening_drive_limit_min=240))
    assert all_ids(on.days) == ["NEAR", "FAR"]


def test_fixed_schedule_follows_the_same_rules():
    t = trip(day_starts=[time(8, 0), time(5, 30)], evening_drive_limit_min=120)
    result, g = schedule([NEAR, FAR, HIKE], t)
    orders = [[s.destination_id for s in d.stops] for d in result.days]
    assert schedule_fixed(orders, g, t) == result.days
    assert schedule_fixed([["NEAR"], ["FAR"]], g, trip()) is None  # without the evening drive: no


# ---------- All four methods, and the expected direction ----------

@pytest.mark.parametrize("sid", ["S06", "S09"])
def test_all_methods_use_per_day_starts_and_evening_drives(sid, tmp_path):
    sc = next(s for s in build_scenarios() if s.id == sid)
    n = sc.trip.num_days
    t = sc.trip.model_copy(update={"day_starts": [time(6, 0)] * n, "evening_drive_limit_min": 120})
    w = config.OBJECTIVE_WEIGHTS
    naive = run_naive(sc.destinations, t, cache_dir=tmp_path)
    seq = run_sequential(sc.destinations, t, cache_dir=tmp_path)
    jnt = optimize_joint(sc.destinations, t, weights=w, max_iterations=150, restarts=2, cache_dir=tmp_path)
    ex = exact_benchmark(sc.destinations, t, weights=w, cache_dir=tmp_path)
    for r in (naive, seq, jnt, ex):
        first = r.itinerary.days[0].stops
        assert first and to_minutes(first[0].arrival_time) == 6 * 60 + first[0].travel_time_min
    for r in (seq, jnt, ex):  # rebuilds identically under the same rules
        orders = [[s.destination_id for s in d.stops] for d in r.itinerary.days]
        rebuilt = schedule_fixed(orders, r.graph, t)
        assert [d.stops for d in rebuilt] == [d.stops for d in r.itinerary.days]
    assert seq.score.total <= jnt.score.total + 1e-9 <= ex.score.total + 2e-9


def _places(sc, trip_request, tmp_path):
    r = run_sequential(sc.destinations, trip_request, cache_dir=tmp_path)
    return sum(len(d.stops) for d in r.itinerary.days)


def test_early_starts_and_evening_drives_add_places_on_early_closing_trips(tmp_path):
    """Expected direction on the early-closing scenarios: never fewer places, more in total."""
    base = early = evening = 0
    for sc in build_scenarios():
        if "early closing" not in sc.tags:
            continue
        n = sc.trip.num_days
        b = _places(sc, sc.trip, tmp_path)
        e = _places(sc, sc.trip.model_copy(update={"day_starts": [time(6, 0)] * n}), tmp_path)
        v = _places(sc, sc.trip.model_copy(update={"evening_drive_limit_min": 120}), tmp_path)
        assert e >= b and v >= b, sc.id
        base, early, evening = base + b, early + e, evening + v
    assert early > base and evening > base
