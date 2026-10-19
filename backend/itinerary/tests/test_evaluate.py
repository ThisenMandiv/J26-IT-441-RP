"""Quick test that scripts/evaluate.py runs end to end on two small scenarios."""

import pandas as pd
import pytest

from scripts.evaluate import (EXACT, JOINT, NAIVE, RESULTS_DIR, SEQ, TABLE_FILES, VERDICT_METRICS, report,
                              run_evaluation, summarise, verdict, verdict_metrics)
from scripts.evaluate_v3 import _one_setting_summary, overridden
from src import config
from src.scenarios import build_scenarios

WEIGHTS = {"default": config.OBJECTIVE_WEIGHTS,
           "time": config.EVALUATION_WEIGHT_SETTINGS["time"]}


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    out = tmp_path_factory.mktemp("results")
    small = [s for s in build_scenarios() if s.id in ("S06", "S09")]  # both 1-day trips, <= 8 places
    tables = run_evaluation(small, WEIGHTS, out_dir=out,
                            cache_dir=tmp_path_factory.mktemp("cache"), max_iterations=100)
    return out, tables, small


def test_default_output_is_v3_folder():
    assert RESULTS_DIR == config.DATA_DIR / "results" / "v3"  # v1 and v2 results are never overwritten


def test_writes_all_files(run):
    out, _, _ = run
    for name in (*TABLE_FILES.values(), "travel_time.png", "budget_adherence.png",
                 "summary_metrics.png", "exact_gap.png"):
        assert (out / name).stat().st_size > 0, name


def test_results_rows_and_columns(run):
    out, tables, _ = run
    results = tables["results"]
    assert len(results) == 2 * 2 * 4  # scenarios x weight settings x methods (both small: exact runs)
    assert set(results["method"]) == {NAIVE, SEQ, JOINT, EXACT}
    for col in ("scenario_id", "method", "travel_min", "within_budget", "overrun_lkr", "conflicts",
                "places_scheduled", "places_unscheduled", "objective_score", "runtime_s",
                "travel_min_per_place", "score_collected", "wait_min"):
        assert col in results.columns, col
    assert set(results["within_budget"]) <= {"yes", "no"}
    assert len(pd.read_csv(out / "results.csv")) == len(results)


def test_objective_order_seq_le_joint_le_exact(run):
    _, tables, _ = run
    for _, group in tables["results"].groupby(["scenario_id", "weights"]):
        obj = group.set_index("method")["objective_score"]
        assert obj[SEQ] <= obj[JOINT] <= obj[EXACT] + 1e-9  # joint starts from sequential; exact is the optimum


def test_only_naive_can_have_conflicts(run):
    _, tables, _ = run
    results = tables["results"]
    assert (results[results["method"] != NAIVE]["conflicts"] == 0).all()


def test_summary_has_per_scenario_and_mean_rows(run):
    _, tables, _ = run
    summary = tables["summary"]
    per = summary[summary["scenario_id"] != "MEAN"]
    assert len(per) == 4
    assert set(summary[summary["scenario_id"] == "MEAN"]["weights"]) == {"default", "time", "all"}
    assert set(per["verdict"]) <= {"better", "same", "mixed", "worse"}


def test_method_means_and_exact_gap(run):
    _, tables, _ = run
    means = tables["means"]
    assert len(means) == 2 * 4  # weight settings x methods
    seq = means[means["method"] == SEQ]
    assert (seq["travel_reduction_vs_seq_pct"] == 0).all()  # the reference
    gaps = tables["exact_gap"]
    assert len(gaps) == 4
    assert (gaps["joint_gap"] >= -1e-9).all() and (gaps["seq_gap"] >= gaps["joint_gap"] - 1e-9).all()


def test_report_lists_ties_and_losses(run):
    _, tables, small = run
    text = report(tables, small)
    for heading in ("Mean per method", "Naive baseline", "Gap to the exact optimum", "ties or loses"):
        assert heading in text


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


# ---------- VERDICT_USE_TOTAL_WAIT (version 6) ----------

V6_BASE = {"within_budget": 1, "overrun_lkr": 0, "conflicts": 0, "places_scheduled": 3, "score_collected": 2.5,
           "travel_min_per_place": 60, "wait_min": 5, "total_wait_min": 5}


def test_total_wait_flag_is_off_by_default_and_keeps_the_old_metrics():
    assert config.VERDICT_USE_TOTAL_WAIT is False
    assert verdict_metrics() == VERDICT_METRICS
    # flag off: idle time before lunch does not enter the verdict
    lunch_idle = pd.Series({**V6_BASE, "total_wait_min": 50})
    assert verdict(pd.Series(V6_BASE), lunch_idle) == "same"


def test_total_wait_flag_swaps_wait_for_total_wait():
    s = pd.Series(V6_BASE)
    with overridden(VERDICT_USE_TOTAL_WAIT=True):
        cols = [c for c, _ in verdict_metrics()]
        assert "total_wait_min" in cols and "wait_min" not in cols and len(cols) == len(VERDICT_METRICS)
        assert verdict(s, pd.Series({**V6_BASE, "total_wait_min": 50})) == "worse"  # more idle before lunch
        assert verdict(s, pd.Series({**V6_BASE, "wait_min": 0, "total_wait_min": 0})) == "better"
        # wait_min alone no longer counts (it is inside total_wait_min, so it is not counted twice)
        assert verdict(s, pd.Series({**V6_BASE, "wait_min": 0})) == "same"
        with pytest.raises(KeyError, match="total_wait_min"):
            verdict(s.drop("total_wait_min"), pd.Series(V6_BASE))
    assert config.VERDICT_USE_TOTAL_WAIT is False  # restored


def test_summary_columns_change_only_with_the_flag(run):
    _, tables, _ = run
    assert not any("total_wait" in c for c in tables["summary"].columns)
    results = tables["results"].assign(total_wait_min=tables["results"]["wait_min"])  # no lunch: equal
    with overridden(VERDICT_USE_TOTAL_WAIT=True):
        on = summarise(results)
    assert "diff_total_wait_min" in on.columns
    assert list(on["verdict"]) == list(tables["summary"]["verdict"])  # without lunch nothing can change


@pytest.mark.parametrize("version", ["", "v2", "v3", "v5"])
def test_flag_off_reproduces_saved_verdicts(version):
    folder = config.DATA_DIR / "results" / version
    if not (folder / "summary.csv").exists():
        pytest.skip(f"{folder} not on this machine")
    saved = pd.read_csv(folder / "summary.csv")
    assert list(summarise(pd.read_csv(folder / "results.csv"))["verdict"]) == list(saved["verdict"])


def test_flag_off_reproduces_v5_ablation_verdict_counts():
    folder = config.DATA_DIR / "results" / "v5"
    if not (folder / "ablation.csv").exists():
        pytest.skip("v5 ablation.csv not on this machine")
    runs, saved = pd.read_csv(folder / "ablation.csv"), pd.read_csv(folder / "ablation_summary.csv")
    for _, row in saved.iterrows():
        counts = _one_setting_summary(runs[runs["setting"] == row["setting"]])
        assert [counts[v] for v in ("better", "same", "mixed", "worse")] == \
               [row[v] for v in ("better", "same", "mixed", "worse")], row["setting"]
