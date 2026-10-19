"""Golden snapshot of the plans BEFORE the version 5 rules (transport modes, hill speeds,
lunch, per-day starts, daily costs) were added.

tests/data/golden_plans.json was written ONCE by running this file on the code as it was
before version 5:

    venv\\Scripts\\python.exe tests\\golden_plans.py

test_flags_off.py rebuilds the same plans with every new flag OFF and checks they are
identical, field by field. Do not regenerate the file after changing src/: it would then
only compare the new code with itself.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # allow running this file directly

from src import config  # noqa: E402
from src.exact import exact_benchmark  # noqa: E402
from src.joint import optimize_joint  # noqa: E402
from src.pipeline import run_naive, run_sequential  # noqa: E402
from src.scenarios import build_scenarios  # noqa: E402

GOLDEN_FILE = Path(__file__).resolve().parent / "data" / "golden_plans.json"

# Every scenario for the fast baselines; a mix of small and hard ones for joint and exact.
JOINT_SCENARIOS = ("S03", "S06", "S09", "S11", "S13", "S14")
EXACT_SCENARIOS = ("S04", "S06", "S08", "S09")
JOINT_ITERATIONS, JOINT_RESTARTS = 150, 2  # small, so the test stays quick
WEIGHT_NAMES = ("default", "budget")

# Fields that existed before version 5. New fields are not compared (they did not exist).
STOP_FIELDS = ("destination_id", "name", "arrival_time", "wait_min", "departure_time",
               "travel_time_min", "travel_cost_lkr", "entry_cost_lkr", "score")
DAY_FIELDS = ("day", "daily_budget_lkr", "daily_cost_lkr", "over_budget")


def plan_record(result) -> dict:
    """The parts of a result that must not change when every new flag is off."""
    it = result.itinerary
    return {
        "score": result.score.total,
        "total_cost_lkr": it.total_cost_lkr,
        "over_budget": it.over_budget,
        "days": [{**{f: str(getattr(d, f)) for f in DAY_FIELDS},
                  "stops": [{f: str(getattr(s, f)) for f in STOP_FIELDS} for s in d.stops]}
                 for d in it.days],
        "unscheduled": [[u.destination_id, u.reason] for u in it.unscheduled],
    }


def build_snapshot(cache_dir) -> dict:
    snapshot = {}
    for sc in build_scenarios():
        snapshot[f"{sc.id}/naive"] = plan_record(run_naive(sc.destinations, sc.trip, cache_dir=cache_dir))
        snapshot[f"{sc.id}/sequential"] = plan_record(run_sequential(sc.destinations, sc.trip,
                                                                     cache_dir=cache_dir))
        for wname in WEIGHT_NAMES:
            weights = config.EVALUATION_WEIGHT_SETTINGS[wname]
            if sc.id in JOINT_SCENARIOS:
                r = optimize_joint(sc.destinations, sc.trip, weights=weights, max_iterations=JOINT_ITERATIONS,
                                   restarts=JOINT_RESTARTS, seed=config.JOINT_SEED, cache_dir=cache_dir)
                snapshot[f"{sc.id}/joint/{wname}"] = plan_record(r)
            if sc.id in EXACT_SCENARIOS:
                r = exact_benchmark(sc.destinations, sc.trip, weights=weights, cache_dir=cache_dir)
                snapshot[f"{sc.id}/exact/{wname}"] = plan_record(r)
    return snapshot


if __name__ == "__main__":
    import tempfile

    if GOLDEN_FILE.exists():
        sys.exit(f"{GOLDEN_FILE} already exists; it must not be regenerated (see the docstring)")
    with tempfile.TemporaryDirectory() as tmp:
        data = build_snapshot(tmp)
    GOLDEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    GOLDEN_FILE.write_text(json.dumps(data, indent=1), encoding="utf-8")
    print(f"wrote {len(data)} plans to {GOLDEN_FILE}")
