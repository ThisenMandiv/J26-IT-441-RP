"""Repeatable test trips for evaluating joint vs sequential (scripts/evaluate.py).

build_scenarios() returns the same 15 trips every time. Each trip has:
- a subset of the 15 mock places (fixed lists, or a random sample with a FIXED seed)
- num_days 1..5, a budget level (tight / medium / generous), a start town
- optionally earlier closing times or a late day start ("hard" cases)

The scenarios were written down once, before looking at any results, and are not
tuned to favour either method. All values are APPROX mock values, not real data.
"""

import random
from collections.abc import Iterable, Sequence
from datetime import time
from typing import NamedTuple

from src import config
from src.loader import load_destinations
from src.models import Destination, TripRequest

# Start points (lat, lng). APPROX town-centre coordinates.
STARTS = {
    "Colombo": (6.9344, 79.8428),
    "Kandy": (7.2906, 80.6337),
    "Galle": (6.0535, 80.2210),
    "Ella": (6.8667, 81.0466),
    "Negombo": (7.2008, 79.8737),
    "Jaffna": (9.6615, 80.0255),
}

# Budget per day, in LKR. APPROX: travel at 100 LKR/km dominates, so a long driving
# day alone costs 15,000-20,000 LKR. "tight" is meant to force hard choices.
BUDGET_PER_DAY_LKR = {"tight": 10_000, "medium": 25_000, "generous": 60_000}

# Fixed place groups (ids from data/destinations.json).
ALL = None  # every place
CULTURAL_TRIANGLE = ["D01", "D02", "D10", "D11", "D12", "D13", "D14"]
SOUTH_COAST = ["D03", "D04", "D07", "D08", "D09"]
HILL_COUNTRY = ["D02", "D04", "D05", "D06", "D13"]

EARLY_CLOSE = time(12, 0)  # "very early closing" used by the hard cases


class Scenario(NamedTuple):
    id: str
    description: str
    destinations: list[Destination]
    trip: TripRequest
    tags: tuple[str, ...]  # e.g. ("tight budget", "early closing")


# ---------- Helpers ----------

def sample_ids(destinations: Sequence[Destination], k: int, seed: int) -> list[str]:
    """k place ids picked at random with a fixed seed (same seed -> same places)."""
    ids = sorted(d.id for d in destinations)
    return sorted(random.Random(seed).sample(ids, k))


def select(destinations: Sequence[Destination], ids: Iterable[str] | None) -> list[Destination]:
    """Places whose id is in ids (all places when ids is None), in file order."""
    if ids is None:
        return list(destinations)
    wanted = set(ids)
    unknown = wanted - {d.id for d in destinations}
    if unknown:
        raise KeyError(f"unknown place ids: {sorted(unknown)}")
    return [d for d in destinations if d.id in wanted]


def with_early_closing(destinations: Sequence[Destination], ids: Iterable[str] | None,
                       closing: time = EARLY_CLOSE) -> list[Destination]:
    """Copy the places, making the chosen ones (all when ids is None) close at `closing`.

    A place never closes before opening + visit time, so it stays possible to visit
    (otherwise it would be unschedulable for both methods and tell us nothing).
    """
    chosen = None if ids is None else set(ids)
    result = []
    for d in destinations:
        if chosen is None or d.id in chosen:
            earliest = d.opening_time.hour * 60 + d.opening_time.minute + d.visit_duration_min
            new_close = max(closing.hour * 60 + closing.minute, earliest)
            d = d.model_copy(update={"closing_time": time(new_close // 60, new_close % 60)})
        result.append(d)
    return result


def make_trip(num_days: int, budget: str, start: str,
              day_start: time = config.DEFAULT_DAY_START,
              day_end: time = config.DEFAULT_DAY_END) -> TripRequest:
    lat, lng = STARTS[start]
    return TripRequest(num_days=num_days, total_budget_lkr=BUDGET_PER_DAY_LKR[budget] * num_days,
                       start_lat=lat, start_lng=lng, day_start=day_start, day_end=day_end)


# ---------- The scenarios ----------

def build_scenarios(destinations: Sequence[Destination] | None = None) -> list[Scenario]:
    """The fixed list of evaluation trips. Loads data/destinations.json if none given."""
    places = load_destinations(config.DESTINATIONS_FILE) if destinations is None else list(destinations)
    random7 = sample_ids(places, 8, seed=7)
    random11 = sample_ids(places, 6, seed=11)
    random23 = sample_ids(places, 5, seed=23)
    random5 = sample_ids(places, 10, seed=5)

    def sc(id, description, ids, num_days, budget, start, tags=(), early=False,
           early_ids=ALL, closing=EARLY_CLOSE, **times) -> Scenario:
        chosen = select(places, ids)
        if early:
            chosen = with_early_closing(chosen, early_ids, closing)
        tags = (f"{budget} budget", *tags) + (("early closing",) if early else ())
        return Scenario(id, description, chosen, make_trip(num_days, budget, start, **times), tags)

    return [
        # --- ordinary trips ---
        sc("S01", "all 15 places, 5 days, generous, from Colombo", ALL, 5, "generous", "Colombo"),
        sc("S02", "all 15 places, 5 days, medium, from Colombo", ALL, 5, "medium", "Colombo"),
        sc("S03", "cultural triangle, 2 days, medium, from Kandy", CULTURAL_TRIANGLE, 2, "medium", "Kandy"),
        sc("S04", "hill country, 2 days, generous, from Kandy", HILL_COUNTRY, 2, "generous", "Kandy"),
        sc("S05", "8 random places (seed 7), 3 days, medium, from Negombo", random7, 3, "medium", "Negombo"),
        sc("S06", "6 random places (seed 11), 1 day, generous, from Kandy", random11, 1, "generous", "Kandy"),
        # --- tight budget ---
        sc("S07", "all 15 places, 3 days, tight, from Colombo", ALL, 3, "tight", "Colombo", ("hard",)),
        sc("S08", "south coast, 2 days, tight, from Galle", SOUTH_COAST, 2, "tight", "Galle", ("hard",)),
        sc("S09", "5 random places (seed 23), 1 day, tight, from Colombo", random23, 1, "tight", "Colombo",
           ("hard",)),
        sc("S10", "all 15 places, 4 days, tight, from Jaffna (far north)", ALL, 4, "tight", "Jaffna", ("hard",)),
        # --- very early closing ---
        sc("S11", "cultural triangle closes 12:00, 2 days, generous, from Kandy", CULTURAL_TRIANGLE, 2,
           "generous", "Kandy", ("hard",), early=True),
        sc("S12", "all 15 close 12:00, 4 days, medium, from Colombo", ALL, 4, "medium", "Colombo",
           ("hard",), early=True),
        sc("S13", "10 random (seed 5), close 13:00, start 10:30, 3 days, medium, from Kandy", random5, 3,
           "medium", "Kandy", ("hard", "late start"), early=True, closing=time(13, 0), day_start=time(10, 30)),
        # --- tight budget AND early closing ---
        sc("S14", "south coast + hill country, half close 12:00, 3 days, tight, from Ella",
           sorted(set(SOUTH_COAST) | set(HILL_COUNTRY)), 3, "tight", "Ella", ("hard",),
           early=True, early_ids=["D03", "D05", "D06", "D08"]),
        sc("S15", "all 15 close 12:00, 5 days, tight, from Galle", ALL, 5, "tight", "Galle",
           ("hard",), early=True),
    ]


# ---------- Scalability scenarios (version 3): real + SYNTHETIC places ----------

SCALE_SIZES = (15, 20, 30, 50)  # 15 = the real places only (reference point)
SCALE_PLACES_PER_DAY = 5  # num_days = places / 5, so every size has about the same pressure
SCALE_BUDGETS = ("medium", "tight")


def build_scalability_scenarios(destinations: Sequence[Destination] | None = None) -> list[Scenario]:
    """Larger trips: the 15 real places plus seeded SYNTHETIC ones (src/synthetic.py).

    Fixed before any run: from Colombo, num_days = size / 5, medium and tight budgets.
    Too many places for the exact benchmark, so only naive/sequential/joint can run.
    """
    from src.synthetic import is_synthetic, scaled_destinations  # local: synthetic imports loader too

    real = load_destinations(config.DESTINATIONS_FILE) if destinations is None else list(destinations)
    scenarios = []
    for size in SCALE_SIZES:
        places = scaled_destinations(real, size)
        n_synth = sum(is_synthetic(p) for p in places)
        days = size // SCALE_PLACES_PER_DAY
        for budget in SCALE_BUDGETS:
            tags = (f"{budget} budget", "scalability") + (("synthetic",) if n_synth else ())
            description = (f"{size} places ({len(real)} real + {n_synth} SYNTHETIC), {days} days, "
                           f"{budget}, from Colombo")
            scenarios.append(Scenario(f"L{size}-{budget[0].upper()}", description, places,
                                      make_trip(days, budget, "Colombo"), tags))
    return scenarios
