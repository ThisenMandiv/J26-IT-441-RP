"""Tests for src/synthetic.py: synthetic places are valid, repeatable and clearly marked."""

import pytest

from src import config
from src.loader import _check_rules, load_destinations
from src.synthetic import (SYNTH_CATEGORY, is_synthetic, scaled_destinations, synthetic_destinations)


@pytest.fixture(scope="module")
def real():
    return load_destinations(config.DESTINATIONS_FILE)


@pytest.mark.parametrize("total", [20, 30, 50])
def test_scaled_set_size_and_real_places_kept(real, total):
    places = scaled_destinations(real, total)
    assert len(places) == total
    assert places[:len(real)] == real  # the real places are unchanged and come first
    assert sum(is_synthetic(p) for p in places) == total - len(real)
    assert len({p.id for p in places}) == total  # unique ids


def test_clearly_marked_as_synthetic(real):
    for p in synthetic_destinations(real, 35):
        assert p.id.startswith("SYN") and p.name.startswith("SYNTHETIC")
        assert p.category == SYNTH_CATEGORY
    assert not any(is_synthetic(p) for p in real)


def test_valid_by_loader_rules(real):
    for p in synthetic_destinations(real, 35):
        assert _check_rules(p) == []  # inside Sri Lanka, closes after opening, cost >= 0, ...
        assert 0.0 <= p.score <= 1.0


def test_repeatable_and_nested(real):
    assert synthetic_destinations(real, 35) == synthetic_destinations(real, 35)  # same seed
    assert synthetic_destinations(real, 35, seed=1) != synthetic_destinations(real, 35)
    assert scaled_destinations(real, 30) == scaled_destinations(real, 50)[:30]  # bigger contains smaller


def test_place_fits_in_a_normal_day(real):
    """Every synthetic visit fits its own opening hours, so no place is impossible by construction."""
    for p in synthetic_destinations(real, 35):
        open_min = (p.closing_time.hour - p.opening_time.hour) * 60
        assert p.visit_duration_min <= open_min


def test_bad_inputs(real):
    with pytest.raises(ValueError):
        scaled_destinations(real, 10)  # fewer than the real places
    with pytest.raises(ValueError):
        synthetic_destinations([], 5)
