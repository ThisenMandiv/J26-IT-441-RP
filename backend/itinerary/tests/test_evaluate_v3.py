"""Quick tests for scripts/evaluate_v3.py on tiny inputs (the full run is done by hand)."""

import pandas as pd
import pytest

from scripts.evaluate import JOINT, NAIVE, SEQ
from scripts.evaluate_v3 import (CONCLUSIONS, DEFAULT_SETTING, RESULTS_DIR, SENSITIVITY_SETTINGS,
                                 objective_check, overridden, report_v3, run_v3)
from src import config
from src.scenarios import build_scalability_scenarios

WEIGHTS = {"default": config.OBJECTIVE_WEIGHTS}


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    out = tmp_path_factory.mktemp("v3")
    scale = build_scalability_scenarios()[:2]  # the 15 real places, medium and tight
    tables = run_v3(out_dir=out, cache_dir=tmp_path_factory.mktemp("cache"), max_iterations=60,
                    scenario_ids=["S06", "S09"], scale_scenarios=scale, sensitivity_ids=["S06", "S09"],
                    weight_settings=WEIGHTS, v2_path=out / "missing.csv")
    return out, tables


def test_default_output_is_v3_and_v1_v2_are_protected(tmp_path):
    assert RESULTS_DIR == config.DATA_DIR / "results" / "v3"
    for folder in (config.DATA_DIR / "results", config.DATA_DIR / "results" / "v2"):
        with pytest.raises(ValueError, match="refusing"):
            run_v3(out_dir=folder, cache_dir=tmp_path)


def test_writes_all_tables(run):
    out, _ = run
    for name in ("results", "summary", "scalability", "scalability_summary", "sensitivity",
                 "sensitivity_summary", "ties_and_losses"):
        assert (out / f"{name}.csv").exists(), name


def test_scalability_has_seq_and_joint_only(run):
    _, tables = run
    scale = tables["scalability"]
    assert set(scale["method"]) == {SEQ, JOINT}
    s = tables["scalability_summary"]
    assert len(s) == 2 and (s["obj_gain"] >= -1e-9).all()  # joint never below sequential
    assert (scale["conflicts"] == 0).all()


def test_sensitivity_covers_every_setting_and_restores_config(run):
    _, tables = run
    summary = tables["sensitivity_summary"]
    assert list(summary["setting"]) == [label for label, _, _ in SENSITIVITY_SETTINGS]
    assert summary.loc[summary["setting"] == DEFAULT_SETTING, "conclusions_same"].item()
    for name in CONCLUSIONS:
        assert name in summary.columns
    assert config.COVERAGE_PENALTY == 20.0 and config.JOINT_ANNEAL_START_TEMP == 2.0  # restored


def test_overridden_restores_even_on_error():
    with pytest.raises(RuntimeError):
        with overridden(COVERAGE_PENALTY=99.0):
            assert config.COVERAGE_PENALTY == 99.0
            raise RuntimeError
    assert config.COVERAGE_PENALTY == 20.0
    with pytest.raises(AttributeError):
        with overridden(NOT_A_SETTING=1):
            pass


def test_coverage_setting_changes_the_objective(run):
    _, tables = run
    sens = tables["sensitivity"]
    seq = sens[(sens["method"] == SEQ)].pivot_table(index="scenario_id", columns="setting",
                                                    values="objective_score")
    # same plans; only scenarios with a coverage shortfall would differ, never the annealing ones
    assert (seq["T 8->0.04"] == seq[DEFAULT_SETTING]).all()


def test_objective_check(tmp_path):
    """Naive with 2 conflicts drops by 2 x penalty (expected); a changed sequential run is flagged."""
    keys = {"scenario_id": ["S1"] * 3, "weights": ["default"] * 3, "method": [NAIVE, SEQ, JOINT]}
    v2 = pd.DataFrame({**keys, "objective_score": [30.0, 10.0, 12.0], "conflicts": [2, 0, 0]})
    v2.to_csv(tmp_path / "v2.csv", index=False)
    v3 = pd.DataFrame({**keys, "objective_score": [30.0 - 2 * config.CONFLICT_PENALTY, 10.0, 12.0]})
    check = objective_check(v3, tmp_path / "v2.csv")
    assert list(check["changed"]) == [True, False, False] and check["expected"].all()
    v3_bad = v3.assign(objective_score=[30.0 - 2 * config.CONFLICT_PENALTY, 9.0, 12.0])
    assert list(objective_check(v3_bad, tmp_path / "v2.csv")["expected"]) == [True, False, True]


def test_report_mentions_every_part(run):
    _, tables = run
    text = report_v3(tables)
    for heading in ("PART 1", "PART 2", "PART 3", "PART 4", "ties or loses"):
        assert heading in text
