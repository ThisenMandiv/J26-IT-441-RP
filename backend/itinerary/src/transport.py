"""Transport modes per leg: car, bus or walking (version 5, behind config.USE_TRANSPORT_MODES).

Every leg (graph edge) gets the mode with the lowest weighted cost for THIS traveller:

    leg value = w_travel_time x hours + w_spend x LKR / OBJECTIVE_MONEY_SCALE_LKR

with the same weights and scales as the travel and spend terms of the objective
(src/objective.py). So a time-focused traveller (high w_travel_time) takes the car, and a
budget traveller (high w_spend) takes the bus whenever the time it adds is worth less to
them than the money it saves. Ties go to the first mode in config.TRANSPORT_MODES (car).

A mode's time = driving time x AVG_ROAD_SPEED_KMH / mode speed + its wait_min.
The car's speed is AVG_ROAD_SPEED_KMH, so a car leg is exactly the old driving estimate.
All speeds, rates and waits are APPROX values from src/config.py.
"""

from collections.abc import Mapping
from typing import NamedTuple

from src import config


class ModeOption(NamedTuple):
    mode: str
    duration_min: float
    cost_lkr: float


def mode_options(distance_km: float, driving_min: float) -> list[ModeOption]:
    """Time and cost of this leg by every mode that is allowed for its length."""
    options = []
    for name, m in config.TRANSPORT_MODES.items():
        if m["max_km"] is not None and distance_km > m["max_km"]:
            continue
        duration = driving_min * config.AVG_ROAD_SPEED_KMH / m["speed_kmh"] + m["wait_min"]
        options.append(ModeOption(name, round(duration, 2), round(distance_km * m["cost_per_km_lkr"], 2)))
    return options


def leg_value(option: ModeOption, weights: Mapping[str, float]) -> float:
    """What this option costs the traveller in objective points (lower is better)."""
    return (weights["travel_time"] * option.duration_min / config.OBJECTIVE_TIME_SCALE_MIN
            + weights["spend"] * option.cost_lkr / config.OBJECTIVE_MONEY_SCALE_LKR)


def choose_mode(distance_km: float, driving_min: float, weights: Mapping[str, float]) -> ModeOption:
    """The option with the lowest leg value (first listed mode wins a tie)."""
    options = mode_options(distance_km, driving_min)
    if not options:
        raise ValueError(f"no transport mode allows a {distance_km} km leg")
    return min(options, key=lambda o: leg_value(o, weights))  # min() keeps the first of equal values


def min_cost_per_km() -> float:
    """Cheapest LKR per km any leg can cost right now (lower bound for the A* heuristic)."""
    if not config.USE_TRANSPORT_MODES:
        return config.MIN_TRAVEL_COST_PER_KM_LKR
    return min(config.MIN_TRAVEL_COST_PER_KM_LKR,
               *(m["cost_per_km_lkr"] for m in config.TRANSPORT_MODES.values()))
