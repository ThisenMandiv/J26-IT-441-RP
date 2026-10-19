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
        "coverage": 0.0,  # 2 of 3 places visited, floor needs ceil(0.3 x 3) = 1
        "conflict": 0.0,  # no graph given, so opening hours are not checked
    })
    assert result.total == pytest.approx(sum(b["terms"].values()))
    assert b["total"] == result.total


def test_empty_plan_scores_zero():
    assert score([DayPlan(day=1)]).total == 0


def test_missing_weight_raises():
    weights = {k: v for k, v in config.OBJECTIVE_WEIGHTS.items() if k != "overrun"}
    with pytest.raises(KeyError, match="overrun"):
        score(two_stop_day(), weights=weights)


# ---------- Coverage floor: an (almost) empty plan never wins ----------

def five_places_trip_plan(entry=3000.0, travel_cost=6000.0) -> list[DayPlan]:
    """A modest real plan: 2 of 5 places, 1 hour drive each, 18,000 LKR in total."""
    return [DayPlan(day=1, stops=[stop("A", travel_min=60, entry=entry, travel_cost=travel_cost),
                                  stop("B", travel_min=60, entry=entry, travel_cost=travel_cost)])]


def left_out(*ids) -> list[UnscheduledStop]:
    return [UnscheduledStop(destination_id=i, name=f"Place {i}", reason="test") for i in ids]


def test_coverage_shortfall():
    from src.objective import coverage_shortfall
    assert coverage_shortfall(0, 5, floor=0.3) == 2  # ceil(1.5)
    assert coverage_shortfall(2, 5, floor=0.3) == 0
    assert coverage_shortfall(1, 10, floor=0.3) == 2  # 0.3 x 10 is exactly 3, not 4
    assert coverage_shortfall(0, 0, floor=0.3) == 0  # nothing to visit, nothing missing
    assert coverage_shortfall(9, 10, floor=0.5) == 0


@pytest.mark.parametrize("weight_name", list(config.EVALUATION_WEIGHT_SETTINGS))
@pytest.mark.parametrize("budget", [50_000.0, 10_000.0])  # within budget, and 8,000 LKR over
def test_empty_plan_scores_below_plan_with_places(weight_name, budget):
    weights = config.EVALUATION_WEIGHT_SETTINGS[weight_name]
    real = score(five_places_trip_plan(), budget=budget, unscheduled=left_out("C", "D", "E"),
                 weights=weights)
    empty = score([DayPlan(day=1)], budget=budget, unscheduled=left_out("A", "B", "C", "D", "E"),
                  weights=weights)
    assert empty.breakdown["coverage_shortfall"] == 2 and real.breakdown["coverage_shortfall"] == 0
    assert empty.total < real.total


def test_coverage_term_in_breakdown():
    empty = score([DayPlan(day=1)], unscheduled=left_out("A", "B", "C", "D", "E"))
    assert empty.breakdown["terms"]["coverage"] == -config.COVERAGE_PENALTY * 2
    assert empty.total == pytest.approx(-config.OBJECTIVE_WEIGHTS["unscheduled"] * 5
                                        - config.COVERAGE_PENALTY * 2)


@pytest.fixture(scope="module")
def sequential_runs(tmp_path_factory):
    from src.pipeline import run_sequential
    from src.scenarios import build_scenarios
    cache = tmp_path_factory.mktemp("cache")
    return [(sc, run_sequential(sc.destinations, sc.trip, cache_dir=cache)) for sc in build_scenarios()]


@pytest.mark.parametrize("weight_name", list(config.EVALUATION_WEIGHT_SETTINGS))
def test_sequential_beats_empty_plan_in_every_scenario(sequential_runs, weight_name):
    """Before the floor, the empty plan won 6 of these 45 cases (S07-S10, tight budgets)."""
    weights = config.EVALUATION_WEIGHT_SETTINGS[weight_name]
    for sc, seq in sequential_runs:
        it = seq.itinerary
        empty_days = [DayPlan(day=d + 1) for d in range(sc.trip.num_days)]
        empty_left = left_out(*(d.id for d in sc.destinations))
        empty = score_plan(empty_days, empty_left,
                           check_overruns(empty_days, allocate_budget(empty_days, sc.trip)), weights)
        real = score_plan(it.days, it.unscheduled, seq.budget_report, weights)
        assert empty.total < real.total, sc.id


@pytest.mark.parametrize("weight_name", list(config.EVALUATION_WEIGHT_SETTINGS))
def test_sequential_beats_best_one_place_plan_in_every_scenario(sequential_runs, weight_name):
    """'Almost nothing': the best plan that visits a single place still scores below sequential
    (in scenarios where sequential itself visits more than one place)."""
    from src.scheduler import schedule_fixed
    weights = config.EVALUATION_WEIGHT_SETTINGS[weight_name]
    for sc, seq in sequential_runs:
        it = seq.itinerary
        if sum(len(d.stops) for d in it.days) <= 1:
            continue
        best_one = -float("inf")
        for d in sc.destinations:
            days = schedule_fixed([[d.id]] + [[]] * (sc.trip.num_days - 1), seq.graph, sc.trip)
            if days is None:
                continue  # this place cannot be visited first thing on day 1
            left = left_out(*(x.id for x in sc.destinations if x.id != d.id))
            report = check_overruns(days, allocate_budget(days, sc.trip))
            best_one = max(best_one, score_plan(days, left, report, weights).total)
        real = score_plan(it.days, it.unscheduled, seq.budget_report, weights)
        assert best_one < real.total, sc.id
