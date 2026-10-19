"""Quick tests for scripts/evaluate_v5.py on tiny inputs (the full run is done by hand)."""

import pandas as pd
import pytest

from scripts.evaluate import JOINT
from scripts.evaluate_v5 import (ABLATION, ALL_LABEL, OFF_LABEL, RESULTS_DIR, V3_RESULTS, V5_FLAGS, early_start,
                                 report_v5, reproduction, run_v5)
from src import config
from src.budget import COST_CATEGORIES
from src.scenarios import build_scalability_scenarios, build_scenarios

WEIGHTS = {"default": config.OBJECTIVE_WEIGHTS, "budget": config.EVALUATION_WEIGHT_SETTINGS["budget"]}


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    out = tmp_path_factory.mktemp("v5")
    tables = run_v5(out_dir=out, cache_dir=tmp_path_factory.mktemp("cache"), max_iterations=60,
                    scenario_ids=["S06", "S09"], scale_scenarios=build_scalability_scenarios()[:1],
                    weight_settings=WEIGHTS, ablation=[ABLATION[0], ABLATION[-1]])
    return out, tables


def test_default_output_is_v5_and_older_folders_are_protected(tmp_path):
    assert RESULTS_DIR == config.DATA_DIR / "results" / "v5"
    for v in ("", "v2", "v3", "v4"):
        with pytest.raises(ValueError, match="refusing"):
            run_v5(out_dir=config.DATA_DIR / "results" / v, cache_dir=tmp_path)


def test_writes_all_tables_and_restores_the_flags(run):
    out, _ = run
    for name in ("results", "summary", "reproduction", "rule_usage", "budget_breakdown", "ablation",
                 "ablation_means", "ablation_summary", "scalability", "scalability_summary", "ties_and_losses"):
        assert (out / f"{name}.csv").exists(), name
    assert all(getattr(config, flag) is False for flag in V5_FLAGS)


@pytest.mark.skipif(not V3_RESULTS.exists(), reason="v3 results.csv is not on this machine")
def test_flags_off_reproduces_v3_for_methods_that_do_not_depend_on_iterations(run):
    """naive, sequential and exact do not depend on the joint budget, so they must match v3 exactly."""
    repro = run[1]["reproduction"]
    ours = repro[repro["scenario_id"].isin(["S06", "S09"]) & repro["weights"].isin(WEIGHTS)]
    fixed = ours[ours["method"] != JOINT]
    assert len(fixed) == 2 * 2 * 3 and fixed["matches"].all(), fixed[~fixed["matches"]]


def test_reproduction_flags_any_difference(tmp_path):
    keys = {"scenario_id": ["S1", "S1"], "weights": ["default"] * 2, "method": ["naive", "sequential"]}
    old = pd.DataFrame({**keys, "places_scheduled": [3, 4], "within_budget": ["yes", "no"], "runtime_s": [1, 2]})
    old.to_csv(tmp_path / "v3.csv", index=False)
    same = old.assign(runtime_s=[9, 9])  # runtime is never compared
    assert reproduction(same, tmp_path / "v3.csv")["matches"].all()
    changed = old.assign(places_scheduled=[3, 5])
    r = reproduction(changed, tmp_path / "v3.csv")
    assert list(r["matches"]) == [True, False] and r["differing_columns"].iloc[1] == "places_scheduled"


def test_main_run_uses_the_rules(run):
    _, tables = run
    usage = tables["rule_usage"]
    assert usage["legs_bus"].sum() > 0  # the budget traveller takes buses
    assert usage.set_index(["weights", "method"]).loc[("default", "sequential"), "legs_car"] > 0
    breakdown = tables["budget_breakdown"]
    total = breakdown[[f"cost_{c}" for c in COST_CATEGORIES]].sum(axis=1)
    assert (abs(total - breakdown["total_cost_lkr"]) <= len(COST_CATEGORIES)).all()  # means rounded to 1 LKR
    assert (breakdown["cost_food"] > 0).all() and (breakdown["cost_accommodation"] >= 0).all()


def test_ablation_has_off_each_rule_and_all_on(run):
    _, tables = run
    settings = list(tables["ablation_means"]["setting"].unique())
    assert settings == [OFF_LABEL, ABLATION[0][0], ABLATION[-1][0], ALL_LABEL]
    off = tables["ablation"][tables["ablation"]["setting"] == OFF_LABEL]
    assert (off[["legs_bus", "lunch_stops", "evening_drives", "cost_food"]] == 0).all().all()


def test_early_start_changes_only_days_after_the_first():
    sc = next(s for s in build_scenarios() if s.id == "S13")  # 3 days, late 10:30 start
    t = early_start(sc).trip
    assert [t.start_of_day(d).strftime("%H:%M") for d in (1, 2, 3)] == ["10:30", "06:00", "06:00"]


def test_report_mentions_every_part(run):
    text = report_v5(run[1])
    for heading in ("PART 0", "PART 1", "PART 2", "PART 3", "PART 4", "ties or loses"):
        assert heading in text
