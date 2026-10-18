"""Quick test that scripts/evaluate.py runs end to end on two small scenarios."""

import pandas as pd
import pytest

from scripts.evaluate import JOINT, SEQ, run_evaluation, verdict
from src import config
from src.scenarios import build_scenarios

WEIGHTS = {"default": config.OBJECTIVE_WEIGHTS,
           "time": config.EVALUATION_WEIGHT_SETTINGS["time"]}


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    out = tmp_path_factory.mktemp("results")
    small = [s for s in build_scenarios() if s.id in ("S06", "S09")]  # both 1-day trips
    results, summary = run_evaluation(small, WEIGHTS, out_dir=out,
                                      cache_dir=tmp_path_factory.mktemp("cache"), max_iterations=100)
    return out, results, summary


def test_writes_all_files(run):
    out, _, _ = run
    for name in ("results.csv", "summary.csv", "travel_time.png",
                 "budget_adherence.png", "summary_metrics.png"):
        assert (out / name).stat().st_size > 0, name


def test_results_rows_and_columns(run):
    out, results, _ = run
    assert len(results) == 2 * 2 * 2  # scenarios x weight settings x methods
    assert set(results["method"]) == {SEQ, JOINT}
    for col in ("scenario_id", "method", "travel_min", "within_budget", "overrun_lkr", "conflicts",
                "places_scheduled", "places_unscheduled", "objective_score", "runtime_s",
                "travel_min_per_place", "score_collected", "wait_min"):
        assert col in results.columns, col
    assert set(results["within_budget"]) <= {"yes", "no"}
    assert len(pd.read_csv(out / "results.csv")) == len(results)


def test_joint_never_has_lower_objective(run):
    _, results, _ = run
    for _, group in results.groupby(["scenario_id", "weights"]):
        seq = group[group["method"] == SEQ]["objective_score"].iloc[0]
        jnt = group[group["method"] == JOINT]["objective_score"].iloc[0]
        assert jnt >= seq  # joint starts from the sequential plan


def test_summary_has_per_scenario_and_mean_rows(run):
    _, _, summary = run
    per = summary[summary["scenario_id"] != "MEAN"]
    assert len(per) == 4
    assert set(summary[summary["scenario_id"] == "MEAN"]["weights"]) == {"default", "time", "all"}
    assert set(per["verdict"]) <= {"better", "same", "mixed", "worse"}


def test_verdict():
    base = {"within_budget": 1, "overrun_lkr": 0, "conflicts": 0, "places_scheduled": 3,
            "score_collected": 2.5, "travel_min_per_place": 60, "wait_min": 0}
    s = pd.Series(base)
    assert verdict(s, pd.Series(base)) == "same"
    assert verdict(s, pd.Series({**base, "wait_min": 10})) == "worse"
    assert verdict(s, pd.Series({**base, "travel_min_per_place": 40})) == "better"
    assert verdict(s, pd.Series({**base, "places_scheduled": 4, "wait_min": 10})) == "mixed"
    # an empty plan has no travel per place, so that metric must not count as a win
    empty = {**base, "places_scheduled": 0, "score_collected": 0, "travel_min_per_place": float("nan")}
    assert verdict(s, pd.Series(empty)) == "worse"
