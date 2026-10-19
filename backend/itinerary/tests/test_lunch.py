"""Tests for the lunch break (config.USE_LUNCH_BREAK) in every scheduler."""

from datetime import time

import pytest

from src import config
from src.budget import planned_cost
from src.exact import exact_benchmark
from src.joint import optimize_joint
from src.models import DayPlan
from src.pipeline import run_naive, run_sequential
from src.scenarios import build_scenarios
from src.scheduler import Leg, _try_stop, attempt, close_day, schedule_fixed, timeline, to_minutes

EARLIEST, LATEST = to_minutes(config.LUNCH_WINDOW_START), to_minutes(config.LUNCH_WINDOW_END)
DUR = config.LUNCH_DURATION_MIN
DAY_END = 18 * 60


def node(opening=time(6, 0), closing=time(22, 0), visit=60):
    return {"opening_time": opening, "closing_time": closing, "visit_duration_min": visit}


LEG = Leg(10, 500.0)


@pytest.fixture
def lunch_on(monkeypatch):
    monkeypatch.setattr(config, "USE_LUNCH_BREAK", True)


@pytest.fixture(scope="module")
def scenarios():
    return {s.id: s for s in build_scenarios()}


def check_lunch(day: DayPlan, day_start: time) -> None:
    """Invariants of a day plan under the lunch rule (shared with test_v5_methods)."""
    events = timeline(day)
    for (_, _, end), (_, start, _) in zip(events, events[1:]):
        assert end <= start, f"day {day.day}: overlapping events {events}"
    if day.lunch is not None:
        lunch = day.lunch
        assert EARLIEST <= to_minutes(lunch.start_time) <= LATEST
        assert to_minutes(lunch.end_time) - to_minutes(lunch.start_time) == DUR
        assert to_minutes(lunch.start_time) - to_minutes(lunch.free_time) == lunch.wait_min >= 0
        assert lunch.wait_min <= config.MAX_WAIT_MIN
        assert lunch.food_cost_lkr == config.LUNCH_COST_LKR
        assert day.stops, "an empty day has no lunch stop"
    elif day.stops:
        last = to_minutes(day.stops[-1].departure_time)
        # no lunch only if the day was over before the window, or began after it
        assert last < EARLIEST or to_minutes(day_start) > LATEST or last + DUR > DAY_END, events


# ---------- The rule on one stop ----------

def test_flag_off_attempt_is_the_old_check():
    for clock in (8 * 60, EARLIEST, 12 * 60 + 50, 15 * 60):
        assert attempt(node(), LEG, clock, DAY_END, 60) == _try_stop(node(), LEG, clock, DAY_END, 60)


def test_inside_the_window_lunch_comes_first(lunch_on):
    clock = EARLIEST + 10
    r = attempt(node(), LEG, clock, DAY_END, 60)
    assert r.ok and r.lunch == (clock, clock)
    assert r.arrival == clock + DUR + LEG.duration_min


def test_before_the_window_a_short_visit_goes_first(lunch_on):
    r = attempt(node(visit=60), LEG, 10 * 60, DAY_END, 60)
    assert r.ok and r.lunch is None and r.departure == 10 * 60 + 10 + 60


def test_visit_that_would_cover_the_window_waits_for_lunch(lunch_on):
    clock = 11 * 60 + 45  # a 3-hour visit would end at 14:55, after the latest lunch start
    r = attempt(node(visit=180), LEG, clock, DAY_END, 60)
    assert r.ok and r.lunch == (clock, EARLIEST)  # 45 min idle, within the 60 min limit
    assert r.arrival == EARLIEST + DUR + LEG.duration_min


def test_idle_before_lunch_has_the_same_limit_as_waiting(lunch_on):
    clock = 11 * 60  # lunch first would mean 90 min idle, over the 60 min limit
    r = attempt(node(visit=180), LEG, clock, DAY_END, 60)
    assert not r.ok and r.kind == "early" and "lunch first" in r.reason  # retried later today
    assert attempt(node(visit=180), LEG, clock, DAY_END, 90).ok


def test_lunch_can_make_a_late_opening_place_reachable(lunch_on):
    late = node(opening=time(13, 30))
    clock = 11 * 60 + 30
    assert attempt(late, LEG, clock, DAY_END, 60, lunch_taken=True).kind == "early"  # 110 min wait
    r = attempt(late, LEG, clock, DAY_END, 60)
    assert r.ok and r.lunch is not None


def test_after_the_window_or_lunch_taken_no_lunch(lunch_on):
    assert attempt(node(), LEG, LATEST + 1, DAY_END, 60).lunch is None
    r = attempt(node(), LEG, EARLIEST + 5, DAY_END, 60, lunch_taken=True)
    assert r.lunch is None and r.arrival == EARLIEST + 5 + LEG.duration_min


def test_failure_keeps_the_stop_check_reason(lunch_on):
    r = attempt(node(closing=time(11, 0)), LEG, 10 * 60 + 55, DAY_END, 60)
    assert not r.ok and r.kind == "closed"


def test_close_day(lunch_on):
    assert close_day(EARLIEST + 5, True, False, DAY_END) == (EARLIEST + 5, EARLIEST + 5)
    assert close_day(EARLIEST - 5, True, False, DAY_END) is None  # day over before the window
    assert close_day(EARLIEST + 5, False, False, DAY_END) is None  # empty day
    assert close_day(EARLIEST + 5, True, True, DAY_END) is None  # already had lunch
    assert close_day(EARLIEST + 5, True, False, EARLIEST + 10) is None  # would end after day end


# ---------- Whole plans ----------

def test_flag_off_plans_have_no_lunch(scenarios, tmp_path):
    r = run_sequential(scenarios["S01"].destinations, scenarios["S01"].trip, cache_dir=tmp_path)
    assert all(d.lunch is None for d in r.itinerary.days)


@pytest.mark.parametrize("sid", ["S01", "S03", "S07", "S12", "S13"])
def test_sequential_and_naive_days_follow_the_rule(scenarios, tmp_path, lunch_on, sid):
    sc = scenarios[sid]
    for r in (run_sequential(sc.destinations, sc.trip, cache_dir=tmp_path),
              run_naive(sc.destinations, sc.trip, cache_dir=tmp_path)):
        for day in r.itinerary.days:
            check_lunch(day, sc.trip.day_start)


def test_lunch_is_in_the_day_cost_and_the_wait(scenarios, tmp_path, lunch_on):
    sc = scenarios["S01"]
    r = run_sequential(sc.destinations, sc.trip, cache_dir=tmp_path)
    lunch_days = [d for d in r.itinerary.days if d.lunch]
    assert lunch_days, "S01 has full days, so at least one lunch"
    for d in r.itinerary.days:
        stops_cost = round(sum(s.entry_cost_lkr + s.travel_cost_lkr for s in d.stops), 2)
        extra = config.LUNCH_COST_LKR if d.lunch else 0.0
        assert planned_cost(d) == d.daily_cost_lkr == pytest.approx(stops_cost + extra)
    wait = sum(s.wait_min for d in r.itinerary.days for s in d.stops) + sum(d.lunch.wait_min for d in lunch_days)
    assert r.score.breakdown["wait_min"] == pytest.approx(wait)


def test_lunch_takes_sightseeing_time_overall(scenarios, tmp_path, monkeypatch):
    """Expected direction over all 15 scenarios: lunch uses 45+ min of each full day, so
    fewer places fit. (Spend per place does NOT reliably rise: the places that drop out are
    often the far, expensive ones. Found when this test was first written.)"""
    def totals():
        places = lunches = 0
        for sc in scenarios.values():
            r = run_sequential(sc.destinations, sc.trip, cache_dir=tmp_path)
            places += sum(len(d.stops) for d in r.itinerary.days)
            lunches += sum(d.lunch is not None for d in r.itinerary.days)
        return places, lunches

    off = totals()
    monkeypatch.setattr(config, "USE_LUNCH_BREAK", True)
    on = totals()
    assert off[1] == 0 and on[1] > 0
    assert on[0] < off[0]


def test_fixed_schedule_rebuilds_the_greedy_plan(scenarios, tmp_path, lunch_on):
    """schedule_fixed (joint, exact) gives exactly the greedy plan for the same day orders."""
    for sid in ("S01", "S07", "S13"):
        sc = scenarios[sid]
        r = run_sequential(sc.destinations, sc.trip, cache_dir=tmp_path)
        orders = [[s.destination_id for s in d.stops] for d in r.itinerary.days]
        rebuilt = schedule_fixed(orders, r.graph, sc.trip)
        for old, new in zip(r.itinerary.days, rebuilt):
            assert (old.stops, old.lunch, old.daily_cost_lkr) == (new.stops, new.lunch, new.daily_cost_lkr)


def test_joint_and_exact_follow_the_rule_and_keep_their_order(scenarios, tmp_path, lunch_on):
    sc = scenarios["S06"]  # 6 places, 1 day: small enough for the exact benchmark
    w = config.OBJECTIVE_WEIGHTS
    seq = run_sequential(sc.destinations, sc.trip, cache_dir=tmp_path)
    jnt = optimize_joint(sc.destinations, sc.trip, weights=w, max_iterations=150, restarts=2, cache_dir=tmp_path)
    ex = exact_benchmark(sc.destinations, sc.trip, weights=w, cache_dir=tmp_path)
    for r in (jnt, ex):
        for day in r.itinerary.days:
            check_lunch(day, sc.trip.day_start)
        orders = [[s.destination_id for s in d.stops] for d in r.itinerary.days]
        assert schedule_fixed(orders, r.graph, sc.trip) == [d.model_copy(update={"daily_budget_lkr": None,
                                                                                 "over_budget": False})
                                                            for d in r.itinerary.days]
    assert seq.score.total <= jnt.score.total + 1e-9 <= ex.score.total + 2e-9
