"""Tests for src/scenarios.py: the evaluation trips are repeatable and valid."""

from datetime import time

import pytest

from src import config
from src.loader import _check_rules, load_destinations
from src.scenarios import (BUDGET_PER_DAY_LKR, build_scenarios, sample_ids, select,
                           with_early_closing)


@pytest.fixture(scope="module")
def places():
    return load_destinations(config.DESTINATIONS_FILE)


@pytest.fixture(scope="module")
def scenarios(places):
    return build_scenarios(places)


def as_data(scenarios):
    """Everything about the scenarios as plain values, for equality checks."""
    return [(s.id, s.description, s.tags, s.trip.model_dump(),
             [d.model_dump() for d in s.destinations]) for s in scenarios]


def test_repeatable(scenarios, places):
    assert as_data(build_scenarios(places)) == as_data(scenarios)
    assert as_data(build_scenarios()) == as_data(scenarios)  # loads the same file itself


def test_at_least_12_with_unique_ids(scenarios):
    ids = [s.id for s in scenarios]
    assert len(ids) >= 12
    assert len(set(ids)) == len(ids)


def test_inputs_are_valid(scenarios):
    for s in scenarios:
        assert s.destinations, s.id
        assert len({d.id for d in s.destinations}) == len(s.destinations), s.id
        for d in s.destinations:
            assert _check_rules(d) == [], (s.id, d.id)  # same business rules as the loader
        assert s.trip.day_end > s.trip.day_start


def test_covers_the_required_variety(scenarios):
    assert {s.trip.num_days for s in scenarios} == {1, 2, 3, 4, 5}
    budgets = {s.trip.total_budget_lkr / s.trip.num_days for s in scenarios}
    assert budgets == set(BUDGET_PER_DAY_LKR.values())
    assert len({(s.trip.start_lat, s.trip.start_lng) for s in scenarios}) >= 4
    assert len({frozenset(d.id for d in s.destinations) for s in scenarios}) >= 6


def test_has_hard_cases(scenarios):
    tags = [set(s.tags) for s in scenarios]
    assert any("tight budget" in t and "early closing" not in t for t in tags)
    assert any("early closing" in t and "tight budget" not in t for t in tags)
    assert any({"tight budget", "early closing"} <= t for t in tags)


def test_early_closing_scenarios_really_close_early(scenarios, places):
    original = {d.id: d.closing_time for d in places}
    for s in scenarios:
        if "early closing" in s.tags:
            assert any(d.closing_time < original[d.id] for d in s.destinations), s.id


def test_sample_ids_fixed_seed(places):
    assert sample_ids(places, 5, seed=1) == sample_ids(places, 5, seed=1)
    assert sample_ids(places, 5, seed=1) != sample_ids(places, 5, seed=2)
    assert len(set(sample_ids(places, 5, seed=1))) == 5


def test_select(places):
    assert select(places, None) == places
    assert [d.id for d in select(places, ["D03", "D01"])] == ["D01", "D03"]
    with pytest.raises(KeyError):
        select(places, ["NOPE"])


def test_with_early_closing_keeps_visit_possible(places):
    changed = with_early_closing(places, ["D01", "D06"], time(9, 0))
    by_id = {d.id: d for d in changed}
    # D01 opens 07:00, 180 min visit -> cannot close before 10:00
    assert by_id["D01"].closing_time == time(10, 0)
    # D06 opens 06:00, 240 min visit -> 10:00
    assert by_id["D06"].closing_time == time(10, 0)
    # untouched place, and the originals are not modified
    assert by_id["D02"].closing_time == places[1].closing_time
    assert places[0].closing_time == time(17, 30)


# ---------- Scalability scenarios (version 3) ----------

def test_scalability_scenarios(places):
    from src.scenarios import SCALE_SIZES, build_scalability_scenarios
    from src.synthetic import is_synthetic
    scale = build_scalability_scenarios(places)
    assert [len(s.destinations) for s in scale] == [n for n in SCALE_SIZES for _ in range(2)]
    for s in scale:
        n_synth = sum(is_synthetic(d) for d in s.destinations)
        assert n_synth == len(s.destinations) - len(places)
        assert ("synthetic" in s.tags) == (n_synth > 0)  # synthetic runs are always marked
        assert s.trip.num_days == len(s.destinations) // 5
        assert all(_check_rules(d) == [] for d in s.destinations)
    assert len({s.id for s in scale}) == len(scale)
    assert [s.id for s in build_scalability_scenarios()] == [s.id for s in scale]  # repeatable
