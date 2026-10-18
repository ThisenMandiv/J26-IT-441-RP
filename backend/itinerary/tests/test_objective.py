"""Tests for src/objective.py: the single-number plan score and its breakdown."""

from datetime import time

import pytest

from src import config
from src.budget import allocate_budget, check_overruns
from src.models import DayPlan, Stop, TripRequest, UnscheduledStop
from src.objective import score_plan

COLOMBO = (6.9344, 79.8428)


# ---------- Helpers (invented values) ----------

def trip(budget=50_000.0, num_days=1) -> TripRequest:
    return TripRequest(num_days=num_days, total_budget_lkr=budget,
                       start_lat=COLOMBO[0], start_lng=COLOMBO[1])


def stop(id, travel_min=30, entry=1000.0, travel_cost=500.0, wait=0.0, score=0.8) -> Stop:
    return Stop(destination_id=id, name=f"Place {id}", arrival_time=time(9, 0), wait_min=wait,
                departure_time=time(10, 0), travel_time_min=travel_min,
                travel_cost_lkr=travel_cost, entry_cost_lkr=entry, score=score)


def score(days, budget=50_000.0, unscheduled=(), weights=config.OBJECTIVE_WEIGHTS):
    t = trip(budget, num_days=len(days))
    report = check_overruns(days, allocate_budget(days, t))
    return score_plan(days, list(unscheduled), report, weights)


def two_stop_day(travel_min=30) -> list[DayPlan]:
    return [DayPlan(day=1, stops=[stop("A", travel_min), stop("B", travel_min)])]


LEFT_OUT = UnscheduledStop(destination_id="C", name="Place C", reason="test")


# ---------- Required behaviour ----------

def test_less_travel_time_scores_higher():
    short, long = score(two_stop_day(travel_min=20)), score(two_stop_day(travel_min=90))
    assert short.total > long.total
    assert short.breakdown["spend_lkr"] == long.breakdown["spend_lkr"]  # all else equal


def test_unscheduled_stop_lowers_score():
    assert score(two_stop_day(), unscheduled=[LEFT_OUT]).total < score(two_stop_day()).total


def test_overrun_lowers_score():
    within, over = score(two_stop_day(), budget=50_000), score(two_stop_day(), budget=1_000)
    assert within.breakdown["overrun_lkr"] == 0
    assert over.breakdown["overrun_lkr"] > 0
    assert over.total < within.total


def test_changing_a_weight_changes_score():
    heavier = {**config.OBJECTIVE_WEIGHTS, "travel_time": config.OBJECTIVE_WEIGHTS["travel_time"] * 3}
    assert score(two_stop_day(), weights=heavier).total < score(two_stop_day()).total


# ---------- Each term ----------

def test_higher_destination_scores_score_higher():
    low = [DayPlan(day=1, stops=[stop("A", score=0.3)])]
    high = [DayPlan(day=1, stops=[stop("A", score=0.9)])]
    assert score(high).total > score(low).total


def test_waiting_lowers_score():
    waiting = [DayPlan(day=1, stops=[stop("A", wait=45)])]
    assert score(waiting).total < score([DayPlan(day=1, stops=[stop("A")])]).total


def test_spending_more_lowers_score():
    cheap = [DayPlan(day=1, stops=[stop("A", entry=500)])]
    dear = [DayPlan(day=1, stops=[stop("A", entry=5000)])]
    assert score(dear).total < score(cheap).total


def test_breakdown_values_and_total():
    """A: 30 min, 1500 LKR; B: 30 min, 1500 LKR, waits 15 min; C unscheduled; no overrun."""
    days = [DayPlan(day=1, stops=[stop("A"), stop("B", wait=15)])]
    result = score(days, unscheduled=[LEFT_OUT])
    b = result.breakdown
    assert (b["score_sum"], b["travel_min"], b["spend_lkr"], b["wait_min"], b["unscheduled"],
            b["overrun_lkr"]) == (1.6, 60, 3000, 15, 1, 0)
    w = config.OBJECTIVE_WEIGHTS
    assert b["terms"] == pytest.approx({
        "score": w["score"] * 1.6,
        "travel_time": -w["travel_time"] * 1.0,  # 60 min = 1 hour
        "spend": -w["spend"] * 0.3,  # 3000 / 10,000
        "wait": -w["wait"] * 0.25,
        "unscheduled": -w["unscheduled"],
        "overrun": 0.0,
    })
    assert result.total == pytest.approx(sum(b["terms"].values()))
    assert b["total"] == result.total


def test_empty_plan_scores_zero():
    assert score([DayPlan(day=1)]).total == 0


def test_missing_weight_raises():
    weights = {k: v for k, v in config.OBJECTIVE_WEIGHTS.items() if k != "overrun"}
    with pytest.raises(KeyError, match="overrun"):
        score(two_stop_day(), weights=weights)
