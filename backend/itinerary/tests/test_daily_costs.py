"""Tests for accommodation, food and other daily costs (config.USE_DAILY_COSTS) and the
budget breakdown by category."""

import pytest

from src import config
from src.budget import COST_CATEGORIES, cost_breakdown, day_breakdown, planned_cost
from src.exact import exact_benchmark
from src.joint import optimize_joint
from src.pipeline import run_naive, run_sequential
from src.scenarios import build_scenarios
from src.scheduler import living_costs, make_day_plan

NIGHT, FOOD, OTHER, LUNCH = (config.ACCOMMODATION_PER_NIGHT_LKR, config.FOOD_PER_DAY_LKR,
                             config.OTHER_PER_DAY_LKR, config.LUNCH_COST_LKR)


@pytest.fixture
def costs_on(monkeypatch):
    monkeypatch.setattr(config, "USE_DAILY_COSTS", True)


@pytest.fixture(scope="module")
def scenarios():
    return {s.id: s for s in build_scenarios()}


def fixed_costs(num_days: int) -> float:
    """Living costs of a whole trip with the lunch flag off."""
    return num_days * (FOOD + LUNCH + OTHER) + (num_days - 1) * NIGHT


# ---------- One day ----------

def test_living_costs_off_are_zero():
    assert set(living_costs(1, 3).values()) == {0.0}


def test_living_costs_on(costs_on, monkeypatch):
    assert living_costs(1, 3) == {"food_cost_lkr": FOOD + LUNCH, "accommodation_cost_lkr": NIGHT,
                                  "other_cost_lkr": OTHER}
    assert living_costs(3, 3)["accommodation_cost_lkr"] == 0.0  # no night after the last day
    monkeypatch.setattr(config, "USE_LUNCH_BREAK", True)
    assert living_costs(1, 3)["food_cost_lkr"] == FOOD  # lunch is then charged by the lunch stop


def test_empty_day_still_pays_food_and_a_night(costs_on):
    day = make_day_plan(1, [], None, num_days=2)
    assert day.daily_cost_lkr == planned_cost(day) == FOOD + LUNCH + OTHER + NIGHT
    assert day_breakdown(day) == {"accommodation": NIGHT, "transport": 0.0, "food": FOOD + LUNCH,
                                  "activities": 0.0, "other": OTHER}


# ---------- Whole plans ----------

def test_flags_off_breakdown_is_transport_and_activities_only(scenarios, tmp_path):
    r = run_sequential(scenarios["S01"].destinations, scenarios["S01"].trip, cache_dir=tmp_path)
    b = r.itinerary.cost_breakdown
    assert list(b) == list(COST_CATEGORIES)
    assert b["accommodation"] == b["food"] == b["other"] == 0.0
    assert b["transport"] + b["activities"] == pytest.approx(r.itinerary.total_cost_lkr)


def test_sequential_plan_unchanged_and_cost_rises_by_exactly_the_living_costs(scenarios, tmp_path, monkeypatch):
    """Sequential never looks at the budget, so only its cost may change, by a fixed amount."""
    for sid in ("S01", "S07", "S12"):
        sc = scenarios[sid]
        off = run_sequential(sc.destinations, sc.trip, cache_dir=tmp_path)
        monkeypatch.setattr(config, "USE_DAILY_COSTS", True)
        on = run_sequential(sc.destinations, sc.trip, cache_dir=tmp_path)
        monkeypatch.setattr(config, "USE_DAILY_COSTS", False)
        assert [d.stops for d in on.itinerary.days] == [d.stops for d in off.itinerary.days]
        assert on.itinerary.total_cost_lkr - off.itinerary.total_cost_lkr == pytest.approx(
            fixed_costs(sc.trip.num_days))
        assert on.budget_report.trip.overrun_lkr >= off.budget_report.trip.overrun_lkr
        assert on.score.total < off.score.total  # more spend, never a better score


@pytest.mark.parametrize("lunch", [False, True])
def test_breakdown_adds_up_for_every_method(scenarios, tmp_path, costs_on, monkeypatch, lunch):
    monkeypatch.setattr(config, "USE_LUNCH_BREAK", lunch)
    sc = scenarios["S06"]
    w = config.OBJECTIVE_WEIGHTS
    results = [run_naive(sc.destinations, sc.trip, cache_dir=tmp_path),
               run_sequential(sc.destinations, sc.trip, cache_dir=tmp_path),
               optimize_joint(sc.destinations, sc.trip, weights=w, max_iterations=150, restarts=2,
                              cache_dir=tmp_path),
               exact_benchmark(sc.destinations, sc.trip, weights=w, cache_dir=tmp_path)]
    for r in results:
        it = r.itinerary
        assert it.cost_breakdown == cost_breakdown(it.days)
        assert sum(it.cost_breakdown.values()) == pytest.approx(it.total_cost_lkr)
        assert it.cost_breakdown["food"] >= FOOD * sc.trip.num_days
        for d in it.days:
            assert planned_cost(d) == d.daily_cost_lkr
            assert sum(day_breakdown(d).values()) == pytest.approx(d.daily_cost_lkr)
    assert results[1].score.total <= results[2].score.total + 1e-9 <= results[3].score.total + 2e-9


def test_living_costs_push_budget_plans_to_fewer_places(scenarios, tmp_path, monkeypatch):
    """Expected direction: less money left for sights -> the budget-weighted joint plan visits
    fewer places in total. Only plans near the budget limit react: the overrun penalty is
    linear, so a plan already over budget (S09) or far below it has the same trade-off per
    extra place with or without a fixed extra cost. (Found while writing this test: on the
    three tight trips alone nothing changed; S03, S05 and S14 do change.)"""
    w = config.EVALUATION_WEIGHT_SETTINGS["budget"]
    chosen = [scenarios[s] for s in ("S03", "S05", "S07", "S09", "S14")]

    def places():
        return sum(sum(len(d.stops) for d in optimize_joint(sc.destinations, sc.trip, weights=w,
                                                            max_iterations=300, restarts=2,
                                                            cache_dir=tmp_path).itinerary.days)
                   for sc in chosen)

    off = places()
    monkeypatch.setattr(config, "USE_DAILY_COSTS", True)
    assert places() < off
