"""Tests for src/scheduler.py: day filling, waiting, deferring and the opening-hours check."""

import math
from datetime import time

import pytest

from src import config
from src.distance import build_fake_matrix, start_location
from src.graph import build_graph
from src.loader import load_destinations
from src.models import DayPlan, Destination, Stop, TripRequest
from src.routing import shortest_path_matrix
from src.scheduler import schedule_days, schedule_fixed, to_minutes, validate_opening_hours
from src.tsp import nearest_neighbor_order, two_opt

START = config.START_NODE_ID
COLOMBO = (6.9344, 79.8428)


# ---------- Helpers ----------

def trip(num_days=1, day_start=time(8, 0), day_end=time(18, 0)) -> TripRequest:
    return TripRequest(num_days=num_days, total_budget_lkr=100_000, start_lat=COLOMBO[0],
                       start_lng=COLOMBO[1], day_start=day_start, day_end=day_end)


def place(id, opening, closing, visit, km_north=2.0, cost=500.0) -> Destination:
    """Test destination a short drive north of the start (invented values)."""
    return Destination(id=id, name=f"Place {id}", lat=COLOMBO[0] + km_north / 111, lng=COLOMBO[1],
                       category="test", cost_lkr=cost, visit_duration_min=visit,
                       opening_time=opening, closing_time=closing, score=0.5)


def graph_for(destinations, trip_request):
    matrix = build_fake_matrix([start_location(trip_request), *destinations])
    return build_graph(destinations, matrix, trip_request)


def visit_start(stop: Stop) -> float:
    return to_minutes(stop.arrival_time) + stop.wait_min


def ids(day: DayPlan) -> list[str]:
    return [s.destination_id for s in day.stops]


def all_scheduled(result) -> list[str]:
    return [s.destination_id for d in result.days for s in d.stops]


def mock_plan(num_days, top=15):
    dests = sorted(load_destinations(config.DESTINATIONS_FILE), key=lambda d: -d.score)[:top]
    t = trip(num_days)
    g = graph_for(dests, t)
    costs = shortest_path_matrix(g)
    order, _ = two_opt(nearest_neighbor_order(costs), costs)
    return order, g, t, schedule_days(order, g, t)


# ---------- Day limits and opening hours on the mock data ----------

@pytest.mark.parametrize("num_days", [1, 3, 7])
def test_no_day_exceeds_day_end(num_days):
    _, _, t, result = mock_plan(num_days)
    for day in result.days:
        for stop in day.stops:
            assert stop.departure_time <= t.day_end
            assert visit_start(stop) >= to_minutes(t.day_start)


@pytest.mark.parametrize("num_days", [1, 3, 7])
def test_every_stop_within_opening_hours(num_days):
    _, g, _, result = mock_plan(num_days)
    for day in result.days:
        for stop in day.stops:
            node = g.nodes[stop.destination_id]
            assert visit_start(stop) >= to_minutes(node["opening_time"])
            assert stop.departure_time <= node["closing_time"]
            assert to_minutes(stop.departure_time) - visit_start(stop) >= node["visit_duration_min"]
    assert validate_opening_hours(result.days, g) == []


@pytest.mark.parametrize("num_days", [1, 2, 3, 5, 7])
@pytest.mark.parametrize("top", [4, 8, 15])
def test_scheduled_plus_unscheduled_equals_input(num_days, top):
    order, _, _, result = mock_plan(num_days, top)
    scheduled = all_scheduled(result)
    unscheduled = [u.destination_id for u in result.unscheduled]
    assert len(scheduled) + len(unscheduled) == len(order) - 1
    assert sorted(scheduled + unscheduled) == sorted(order[1:])  # each exactly once


def test_stops_in_a_day_do_not_overlap():
    _, _, _, result = mock_plan(7)
    for day in result.days:
        for prev, nxt in zip(day.stops, day.stops[1:]):
            assert to_minutes(nxt.arrival_time) == to_minutes(prev.departure_time) + nxt.travel_time_min


def test_one_day_plan_per_trip_day():
    _, _, _, result = mock_plan(5)
    assert [d.day for d in result.days] == [1, 2, 3, 4, 5]


# ---------- Waiting ----------

def test_waits_when_opening_is_soon():
    a = place("A", time(8, 30), time(17, 0), visit=60)  # ~4 min away, opens 30 min after day start
    t = trip()
    result = schedule_days([START, "A"], graph_for([a], t), t)
    stop = result.days[0].stops[0]
    assert 0 < stop.wait_min <= config.MAX_WAIT_MIN
    assert visit_start(stop) == to_minutes(time(8, 30))
    assert stop.departure_time == time(9, 30)


def test_wait_limit_comes_from_parameter():
    a = place("A", time(8, 30), time(17, 0), visit=60)
    t = trip()
    result = schedule_days([START, "A"], graph_for([a], t), t, max_wait_min=0)
    assert result.days[0].stops == []
    assert "limit 0" in result.unscheduled[0].reason


# ---------- Moving (deferring) ----------

def test_late_opening_stop_is_moved_later_same_day():
    """A opens at 13:00 (wait too long at 08:00), so B goes first and A is retried after it."""
    a = place("A", time(13, 0), time(17, 0), visit=60)
    b = place("B", time(6, 0), time(18, 0), visit=240, km_north=3)
    t = trip()
    result = schedule_days([START, "A", "B"], graph_for([a, b], t), t)
    assert ids(result.days[0]) == ["B", "A"]
    assert visit_start(result.days[0].stops[1]) >= to_minutes(time(13, 0))


def test_closed_stop_is_moved_to_next_day():
    """A closes at 09:00; after B it is too late, so A moves to day 2 morning."""
    b = place("B", time(6, 0), time(18, 0), visit=120)
    a = place("A", time(6, 0), time(9, 0), visit=30, km_north=3)
    t = trip(num_days=2)
    result = schedule_days([START, "B", "A"], graph_for([a, b], t), t)
    assert ids(result.days[0]) == ["B"]
    assert ids(result.days[1]) == ["A"]
    assert result.unscheduled == []


def test_stop_that_does_not_fit_before_day_end_moves_to_next_day():
    b = place("B", time(6, 0), time(22, 0), visit=420)
    a = place("A", time(6, 0), time(22, 0), visit=180, km_north=3)
    t = trip(num_days=2)
    result = schedule_days([START, "B", "A"], graph_for([a, b], t), t)
    assert ids(result.days[0]) == ["B"]
    assert ids(result.days[1]) == ["A"]


def test_next_day_starts_where_previous_day_ended():
    b = place("B", time(6, 0), time(18, 0), visit=120, km_north=50)
    a = place("A", time(6, 0), time(9, 0), visit=30, km_north=52)
    t = trip(num_days=2)
    g = graph_for([a, b], t)
    first = schedule_days([START, "B", "A"], g, t).days[1].stops[0]
    assert first.destination_id == "A"
    assert first.travel_time_min == math.ceil(g.edges["B", "A"]["duration_min"])  # from B, not START


# ---------- Unscheduled ----------

def test_never_fitting_stop_is_unscheduled_with_reason():
    a = place("A", time(10, 0), time(12, 0), visit=300)  # open 120 min, needs 300
    t = trip(num_days=3)
    result = schedule_days([START, "A"], graph_for([a], t), t)
    assert all(d.stops == [] for d in result.days)
    (u,) = result.unscheduled
    assert u.destination_id == "A" and u.name == "Place A"
    assert "visit takes 300 min" in u.reason and "open only 120 min" in u.reason


def test_stop_closed_outside_day_window_is_unscheduled():
    a = place("A", time(19, 0), time(23, 0), visit=60)  # evening only, day ends 18:00
    t = trip()
    (u,) = schedule_days([START, "A"], graph_for([a], t), t).unscheduled
    assert "open only 0 min" in u.reason


def test_out_of_days_stop_is_unscheduled_with_last_reason():
    b = place("B", time(6, 0), time(18, 0), visit=120)
    a = place("A", time(6, 0), time(9, 0), visit=30, km_north=3)
    t = trip(num_days=1)
    result = schedule_days([START, "B", "A"], graph_for([a, b], t), t)
    assert ids(result.days[0]) == ["B"]
    (u,) = result.unscheduled
    assert u.destination_id == "A"
    assert u.reason.startswith("day 1:") and "after closing 09:00" in u.reason


# ---------- num_days = 1 and custom windows ----------

def test_single_day_trip():
    order, _, t, result = mock_plan(num_days=1)
    assert len(result.days) == 1
    assert len(result.days[0].stops) >= 1
    assert len(result.days[0].stops) + len(result.unscheduled) == len(order) - 1


def test_custom_day_window_is_respected():
    a = place("A", time(6, 0), time(20, 0), visit=60)
    b = place("B", time(6, 0), time(20, 0), visit=120, km_north=3)
    t = trip(day_start=time(9, 0), day_end=time(11, 0))
    result = schedule_days([START, "A", "B"], graph_for([a, b], t), t)
    assert result.days[0].stops[0].arrival_time >= time(9, 0)
    assert all(s.departure_time <= time(11, 0) for s in result.days[0].stops)
    assert [u.destination_id for u in result.unscheduled] == ["B"]


def test_start_only_order():
    t = trip(num_days=2)
    result = schedule_days([START], graph_for([], t), t)
    assert [d.stops for d in result.days] == [[], []]
    assert result.unscheduled == []


# ---------- Stop fields and daily cost ----------

def test_stop_fields_and_daily_cost():
    a = place("A", time(6, 0), time(18, 0), visit=60, cost=700)
    t = trip()
    g = graph_for([a], t)
    day = schedule_days([START, "A"], g, t).days[0]
    stop = day.stops[0]
    edge = g.edges[START, "A"]
    assert stop.travel_time_min == math.ceil(edge["duration_min"])  # rounded up
    assert stop.travel_cost_lkr == pytest.approx(edge["cost_lkr"])
    assert stop.entry_cost_lkr == 700
    assert to_minutes(stop.arrival_time) == to_minutes(t.day_start) + stop.travel_time_min
    assert day.daily_cost_lkr == pytest.approx(stop.travel_cost_lkr + 700)
    assert day.daily_budget_lkr is None  # filled in by WBS 3.7


# ---------- Input checks ----------

def test_order_must_start_with_start():
    a = place("A", time(6, 0), time(18, 0), visit=60)
    t = trip()
    with pytest.raises(ValueError, match="must start with"):
        schedule_days(["A"], graph_for([a], t), t)


def test_unknown_stop_raises():
    t = trip()
    with pytest.raises(KeyError, match="not in the graph"):
        schedule_days([START, "Z"], graph_for([], t), t)


# ---------- validate_opening_hours ----------

def _plan(arrival, departure, wait=0.0, stop_id="A") -> list[DayPlan]:
    stop = Stop(destination_id=stop_id, name="x", arrival_time=arrival, wait_min=wait,
                departure_time=departure, travel_time_min=5, travel_cost_lkr=0, entry_cost_lkr=0)
    return [DayPlan(day=1, stops=[stop])]


@pytest.fixture
def one_place_graph():
    t = trip()
    return graph_for([place("A", time(9, 0), time(12, 0), visit=60)], t)


def test_validate_accepts_valid_stop(one_place_graph):
    assert validate_opening_hours(_plan(time(8, 50), time(10, 0), wait=10), one_place_graph) == []


def test_validate_flags_visit_before_opening(one_place_graph):
    (conflict,) = validate_opening_hours(_plan(time(8, 30), time(9, 30)), one_place_graph)
    assert "before opening 09:00" in conflict and conflict.startswith("day 1, A")


def test_validate_flags_leaving_after_closing(one_place_graph):
    (conflict,) = validate_opening_hours(_plan(time(11, 30), time(12, 30)), one_place_graph)
    assert "after closing 12:00" in conflict


def test_validate_flags_short_visit(one_place_graph):
    (conflict,) = validate_opening_hours(_plan(time(10, 0), time(10, 30)), one_place_graph)
    assert "needs 60 min" in conflict


def test_validate_flags_unknown_place(one_place_graph):
    (conflict,) = validate_opening_hours(_plan(time(10, 0), time(11, 0), stop_id="Z"), one_place_graph)
    assert "not in the graph" in conflict


# ---------- schedule_fixed (used by the joint optimizer) ----------

@pytest.mark.parametrize("num_days", [1, 3, 7])
def test_schedule_fixed_rebuilds_greedy_plan_exactly(num_days):
    _, g, t, result = mock_plan(num_days)
    day_orders = [ids(d) for d in result.days]
    assert schedule_fixed(day_orders, g, t) == result.days


def test_schedule_fixed_uses_given_days():
    a = place("A", time(6, 0), time(18, 0), visit=60)
    b = place("B", time(6, 0), time(18, 0), visit=60, km_north=3)
    t = trip(num_days=2)
    days = schedule_fixed([[], ["B", "A"]], graph_for([a, b], t), t)
    assert [ids(d) for d in days] == [[], ["B", "A"]]
    assert days[1].stops[0].travel_time_min == math.ceil(
        graph_for([a, b], t).edges[START, "B"]["duration_min"])  # day 1 empty, so leaves from START


def test_schedule_fixed_returns_none_when_a_stop_does_not_fit():
    b = place("B", time(6, 0), time(18, 0), visit=120)
    a = place("A", time(6, 0), time(9, 0), visit=30, km_north=3)  # closes before B is done
    t = trip()
    assert schedule_fixed([["B", "A"]], graph_for([a, b], t), t) is None
    assert schedule_fixed([["A", "B"]], graph_for([a, b], t), t) is not None


def test_schedule_fixed_checks_day_count():
    t = trip(num_days=2)
    with pytest.raises(ValueError, match="expected 2 days"):
        schedule_fixed([[]], graph_for([], t), t)
