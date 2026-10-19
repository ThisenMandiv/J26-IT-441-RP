"""Quick tests for scripts/evaluate_v6.py on tiny inputs (the full run is done by hand)."""

import math

import pandas as pd
import pytest

from scripts.evaluate import _rescore
from scripts.evaluate_v3 import overridden
from scripts.evaluate_v5 import ABLATION, ALL_LABEL, ALL_ON, V5_FLAGS
from scripts.evaluate_v6 import (RESULTS_DIR, report_v6, run_v6, verdict_change_counts, verdict_changes,
                                 wait_breakeven)
from src import config
from src.joint import optimize_joint
from src.objective import plan_totals
from src.pipeline import run_sequential
from src.scenarios import build_scenarios

WEIGHTS = {"default": config.OBJECTIVE_WEIGHTS, "time": config.EVALUATION_WEIGHT_SETTINGS["time"]}
LUNCH = next(a for a in ABLATION if a[0] == "lunch break")


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    out = tmp_path_factory.mktemp("v6")
    tables = run_v6(out_dir=out, cache_dir=tmp_path_factory.mktemp("cache"), max_iterations=60,
                    scenario_ids=["S06", "S09"], weight_settings=WEIGHTS, ablation=[LUNCH],
                    v5_dir=tmp_path_factory.mktemp("no_v5"))
    return out, tables


def test_default_output_is_v6_and_older_folders_are_protected(tmp_path):
    assert RESULTS_DIR == config.DATA_DIR / "results" / "v6"
    for v in ("", "v2", "v3", "v4", "v5"):
        with pytest.raises(ValueError, match="refusing"):
            run_v6(out_dir=config.DATA_DIR / "results" / v, cache_dir=tmp_path)


def test_writes_all_tables_and_restores_every_flag(run):
    out, _ = run
    for name in ("results", "summary", "ablation", "ablation_summary", "ties_and_losses", "verdict_changes",
                 "verdict_change_counts", "reproduction"):
        assert (out / f"{name}.csv").exists(), name
    assert (out / "ablation" / "lunch_break" / "results.csv").exists()
    assert config.VERDICT_USE_TOTAL_WAIT is False
    assert all(getattr(config, flag) is False for flag in V5_FLAGS)


def test_summary_uses_the_new_rule(run):
    _, tables = run
    assert "diff_total_wait_min" in tables["summary"].columns
    assert list(tables["ablation_summary"]["setting"]) == ["lunch break", ALL_LABEL]


def test_verdict_changes_cover_every_run(run):
    _, tables = run
    changes, counts = tables["verdict_changes"], tables["verdict_change_counts"]
    assert len(changes) == 2 * 2 * 2  # settings x scenarios x weights
    total = counts[counts["setting"] == "TOTAL"].iloc[0]
    assert total["runs"] == len(changes) and total["changed"] == changes["changed"].sum()
    for rule in ("v5_rule", "total_wait"):
        assert sum(total[f"{v}_{rule}"] for v in ("better", "same", "mixed", "worse")) == len(changes)


def test_verdict_changes_on_a_hand_made_table():
    """Joint waits less for opening but idles 30 min before lunch: 'better' becomes 'worse'."""
    base = {"setting": "x", "scenario_id": "S1", "weights": "default", "tags": "", "travel_min": 100,
            "within_budget": "yes", "overrun_lkr": 0, "conflicts": 0, "conflict_rate": 0, "places_scheduled": 3,
            "score_collected": 2.0, "travel_min_per_place": 30}
    df = pd.DataFrame([{**base, "method": "sequential", "wait_min": 10, "total_wait_min": 10},
                       {**base, "method": "joint", "wait_min": 5, "total_wait_min": 35}])
    changes = verdict_changes(df)
    assert list(changes[["verdict_v5_rule", "verdict_total_wait", "changed"]].iloc[0]) == ["better", "worse", True]
    assert verdict_change_counts(changes)["changes"].iloc[0] == "better->worse: 1"


def test_wait_breakeven_formula():
    # joint +1.0 with 30 min (0.5 h) less waiting at w = 1: its lead shrinks 0.5 per unit of w,
    # so it would only vanish at w = 1 - 1.0 / 0.5 = -1, which is not a real weight
    assert wait_breakeven(10.0, 11.0, 60, 30, 1.0) == (-1.0, "never: needs a negative wait weight")
    # joint +0.25 with 30 min less waiting at w = 1: sequential higher below w = 0.5
    assert wait_breakeven(10.0, 10.25, 60, 30, 1.0) == (0.5, "wait weight < 0.5")
    # joint +1.0 but waits 60 min MORE: sequential higher above w = 2
    assert wait_breakeven(10.0, 11.0, 0, 60, 1.0) == (2.0, "wait weight > 2.0")
    value, when = wait_breakeven(10.0, 10.0, 20, 20, 3.0)
    assert math.isnan(value) and when == "never: same waiting"


def test_breakeven_columns_only_on_ties_and_losses(run):
    _, tables = run
    losses = tables["ties_and_losses"]
    assert len(losses) > 0
    for col in ("wait_weight", "seq_wait_obj_min", "joint_wait_obj_min", "wait_breakeven", "seq_scores_higher_if"):
        assert col in losses.columns
    assert set(losses["wait_weight"]) <= {1.0, 3.0}


def test_breakeven_matches_a_real_rescore(tmp_path):
    """Rescoring both real plans at the break-even wait weight gives equal objectives."""
    checked = 0
    with overridden(**ALL_ON):
        for sc in build_scenarios():
            if sc.id not in ("S01", "S07", "S10", "S14"):  # joint and sequential wait differently in v5
                continue
            seq = run_sequential(sc.destinations, sc.trip, cache_dir=tmp_path,
                                 mode_weights=config.OBJECTIVE_WEIGHTS)
            jnt = optimize_joint(sc.destinations, sc.trip, weights=config.OBJECTIVE_WEIGHTS, max_iterations=200,
                                 seed=config.JOINT_SEED, cache_dir=tmp_path)
            waits = [plan_totals(r.itinerary.days, r.itinerary.unscheduled, r.budget_report)["wait_min"]
                     for r in (seq, jnt)]
            w, _ = wait_breakeven(_rescore(seq, config.OBJECTIVE_WEIGHTS), jnt.score.total, *waits, 1.0)
            if math.isnan(w):
                continue
            at_w = {**config.OBJECTIVE_WEIGHTS, "wait": w}
            assert _rescore(seq, at_w) == pytest.approx(_rescore(jnt, at_w), abs=0.01)  # w rounded to 3 places
            checked += 1
    assert checked > 0, "no scenario with different waiting; pick others"


def test_row_v6_adds_the_objective_wait(run):
    _, tables = run
    r = tables["results"]
    assert "objective_wait_min" in r.columns
    assert ((r["objective_wait_min"] - r["total_wait_min"]).abs() <= 0.051).all()  # same total, other rounding


def test_report_mentions_every_part(run):
    text = report_v6(run[1])
    for part in ("Reproduction", "Verdict counts", "break-even", "lunch break"):
        assert part in text
