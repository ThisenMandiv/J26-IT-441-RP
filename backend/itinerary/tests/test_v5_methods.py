"""All version 5 rules on together: naive, sequential, joint and exact use the same rules."""

from datetime import time

import pytest

from tests.test_lunch import check_lunch
from src import config
from src.budget import cost_breakdown, planned_cost
from src.exact import exact_benchmark
from src.joint import optimize_joint
from src.objective import score_plan
from src.pipeline import run_naive, run_sequential
from src.scenarios import build_scenarios
from src.scheduler import living_costs, schedule_fixed

FLAGS = ("USE_TRANSPORT_MODES", "USE_REGION_SPEEDS", "USE_LUNCH_BREAK", "USE_EVENING_DRIVE", "USE_DAILY_COSTS")


@pytest.fixture
def all_on(monkeypatch):
    for flag in FLAGS:
        monkeypatch.setattr(config, flag, True)


def run_all(sc, trip, weights, cache_dir):
    return {
        "naive": run_naive(sc.destinations, trip, cache_dir=cache_dir, mode_weights=weights),
        "sequential": run_sequential(sc.destinations, trip, cache_dir=cache_dir, mode_weights=weights),
        "joint": optimize_joint(sc.destinations, trip, weights=weights, max_iterations=200, restarts=2,
                                cache_dir=cache_dir),
        "exact": exact_benchmark(sc.destinations, trip, weights=weights, cache_dir=cache_dir),
    }


@pytest.mark.parametrize("wname", ["default", "budget", "time"])
@pytest.mark.parametrize("sid", ["S04", "S08", "S09"])
def test_all_rules_on_every_method_follows_them(sid, wname, all_on, tmp_path):
    sc = next(s for s in build_scenarios() if s.id == sid)
    n = sc.trip.num_days
    trip = sc.trip.model_copy(update={"day_starts": [time(6, 30)] + [time(7, 0)] * (n - 1)})
    weights = config.EVALUATION_WEIGHT_SETTINGS[wname]
    results = run_all(sc, trip, weights, tmp_path)

    # same graph (transport modes for these weights, hill speeds) for every method
    edges = {name: list(r.graph.edges(data=True)) for name, r in results.items()}
    assert all(e == edges["naive"] for e in edges.values())
    assert all("mode" in d for _, _, d in edges["naive"])

    for name, r in results.items():
        it = r.itinerary
        for d in it.days:
            check_lunch(d, trip.start_of_day(d.day))
            living = living_costs(d.day, n)
            assert (d.food_cost_lkr, d.accommodation_cost_lkr, d.other_cost_lkr) == tuple(living.values())
            assert planned_cost(d) == d.daily_cost_lkr
            for s in d.stops:
                assert s.travel_mode is not None
        assert it.cost_breakdown == cost_breakdown(it.days)
        assert sum(it.cost_breakdown.values()) == pytest.approx(it.total_cost_lkr)
        first = next((d for d in it.days if d.stops), None)
        if first is not None and first.day == 1:
            assert first.stops[0].arrival_time >= time(6, 30)

    # the three hours-aware methods rebuild identically under schedule_fixed (same timing rules)
    for name in ("sequential", "joint", "exact"):
        r = results[name]
        orders = [[s.destination_id for s in d.stops] for d in r.itinerary.days]
        rebuilt = schedule_fixed(orders, r.graph, trip)
        assert [(d.stops, d.lunch, d.daily_cost_lkr) for d in rebuilt] == \
               [(d.stops, d.lunch, d.daily_cost_lkr) for d in r.itinerary.days], name

    # run_sequential scores with the default weights, so rescore it under these weights first
    s = results["sequential"]
    seq = score_plan(s.itinerary.days, s.itinerary.unscheduled, s.budget_report, weights, s.graph).total
    jnt, ex = results["joint"].score.total, results["exact"].score.total
    assert seq <= jnt + 1e-9 <= ex + 2e-9  # joint never below sequential, exact is the optimum


def test_each_flag_alone_changes_some_plan_and_off_again_restores(monkeypatch, tmp_path):
    """Every flag has an effect on its own, and switching it back off gives the old plan."""
    scenarios = {s.id: s for s in build_scenarios()}
    probe = [scenarios[s] for s in ("S01", "S04", "S12", "S14")]
    budget = config.EVALUATION_WEIGHT_SETTINGS["budget"]

    def plans():
        out = []
        for sc in probe:
            r = run_sequential(sc.destinations, sc.trip, cache_dir=tmp_path, mode_weights=budget)
            out.append([(s.destination_id, s.arrival_time, s.travel_cost_lkr) for d in r.itinerary.days
                        for s in d.stops] + [r.itinerary.total_cost_lkr])
        return out

    base = plans()
    for flag in FLAGS:
        monkeypatch.setattr(config, flag, True)
        assert plans() != base, f"{flag} had no effect"
        monkeypatch.setattr(config, flag, False)
        assert plans() == base, f"{flag} off did not restore the plan"
