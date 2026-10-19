"""SYNTHETIC destinations for the scalability test (version 3). NOT real places.

The mock data has only 15 places. To see how the methods behave on bigger inputs,
scaled_destinations() adds made-up places to the 15 real ones until there are n.
Each synthetic place is clearly marked so it can never be mistaken for real data:

    id        "SYN01", "SYN02", ...
    name      "SYNTHETIC 01 (near Galle Fort)"
    category  "synthetic"

How one synthetic place is made (all choices from a random generator with a FIXED seed,
so the same seed always gives the same places):
    - location: a random real place, moved by up to SYNTH_MAX_OFFSET_DEG (about 25 km)
      in each direction, kept inside the Sri Lanka bounding box
    - cost, visit time, opening and closing time, score: drawn from ranges similar
      to the real mock data (APPROX, invented)

Because the places are generated in order, the 20-place set is the first 5 synthetic
places, the 30-place set the first 15, and so on: a bigger set contains the smaller one.
"""

import random
from collections.abc import Sequence
from datetime import time

from src import config
from src.loader import _check_rules
from src.models import Destination

SYNTH_PREFIX = "SYN"
SYNTH_CATEGORY = "synthetic"
SYNTH_SEED = 2026  # fixed before any scalability run
SYNTH_MAX_OFFSET_DEG = 0.25  # APPROX: about 25 km at Sri Lanka's latitude

# APPROX value ranges, similar to data/destinations.json.
SYNTH_COSTS_LKR = (0, 200, 500, 1000, 2000, 3000, 5000, 7500)
SYNTH_VISIT_MIN = (45, 60, 90, 120, 150, 180)
SYNTH_OPENING = (time(6, 0), time(7, 0), time(8, 0), time(9, 0))
SYNTH_CLOSING = (time(16, 0), time(17, 0), time(18, 0), time(20, 0))
SYNTH_SCORE_RANGE = (0.40, 0.90)  # real places score 0.55-0.95; synthetic ones a little lower


def is_synthetic(destination: Destination) -> bool:
    return destination.category == SYNTH_CATEGORY


def _clamp(value: float, low: float, high: float) -> float:
    return min(high, max(low, value))


def synthetic_destination(number: int, real: Sequence[Destination], rng: random.Random) -> Destination:
    """One made-up place near a random real one."""
    anchor = rng.choice(list(real))
    lat = _clamp(anchor.lat + rng.uniform(-SYNTH_MAX_OFFSET_DEG, SYNTH_MAX_OFFSET_DEG),
                 config.SL_MIN_LAT, config.SL_MAX_LAT)
    lng = _clamp(anchor.lng + rng.uniform(-SYNTH_MAX_OFFSET_DEG, SYNTH_MAX_OFFSET_DEG),
                 config.SL_MIN_LNG, config.SL_MAX_LNG)
    place = Destination(
        id=f"{SYNTH_PREFIX}{number:02d}",
        name=f"SYNTHETIC {number:02d} (near {anchor.name})",
        lat=round(lat, 4), lng=round(lng, 4),
        category=SYNTH_CATEGORY,
        cost_lkr=rng.choice(SYNTH_COSTS_LKR),
        visit_duration_min=rng.choice(SYNTH_VISIT_MIN),
        opening_time=rng.choice(SYNTH_OPENING),
        closing_time=rng.choice(SYNTH_CLOSING),
        score=round(rng.uniform(*SYNTH_SCORE_RANGE), 2),
    )
    problems = _check_rules(place)  # same business rules as the loader
    if problems:
        raise ValueError(f"generated an invalid synthetic place {place.id}: {problems}")
    return place


def synthetic_destinations(real: Sequence[Destination], count: int,
                           seed: int = SYNTH_SEED) -> list[Destination]:
    """`count` synthetic places (SYN01..), repeatable for a given seed."""
    if not real:
        raise ValueError("need at least one real place to place synthetic ones near")
    rng = random.Random(seed)
    return [synthetic_destination(i, real, rng) for i in range(1, count + 1)]


def scaled_destinations(real: Sequence[Destination], total: int,
                        seed: int = SYNTH_SEED) -> list[Destination]:
    """All real places plus enough synthetic ones to reach `total` places."""
    if total < len(real):
        raise ValueError(f"total ({total}) is smaller than the {len(real)} real places")
    return [*real, *synthetic_destinations(real, total - len(real), seed)]
