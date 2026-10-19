"""Quick tests for scripts/evaluate_v4.py on a tiny grid (the full run is done by hand)."""

import pytest

from scripts.evaluate_v4 import RESULTS_DIR, report_v4, run_v4
from src import config
from src.scenarios import build_scalability_scenarios


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    out = tmp_path_factory.mktemp("v4")
    trips = build_scalability_scenarios()[:2]  # the 15 real places, medium and tight
    tables = run_v4(out_dir=out, cache_dir=tmp_path_factory.mktemp("cache"), grid_scenarios=trips,
                    multipliers=(1, 2), restarts=(2,), base_iterations=40)
    return out, tables


def test_default_output_is_v4_and_older_folders_are_protected(tmp_path):
    assert RESULTS_DIR == config.DATA_DIR / "results" / "v4"
    for folder in (config.DATA_DIR / "results", *(config.DATA_DIR / "results" / v for v in ("v2", "v3"))):
        with pytest.raises(ValueError, match="refusing"):
            run_v4(out_dir=folder, cache_dir=tmp_path)


def test_writes_all_tables(run):
    out, _ = run
    for name in ("budget_grid", "search_log", "block_grid", "block_search_log", "block_vs_grid",
                 "ties_and_losses"):
        assert (out / f"{name}.csv").exists(), name


def test_grid_has_every_setting_and_never_loses(run):
    _, tables = run
    for key in ("budget_grid", "block_grid"):
        grid = tables[key]
        assert len(grid) == 2 * 2 * 1  # trips x multipliers x restarts
        assert set(grid["iterations"]) == {40, 80}
        assert (grid["obj_gain"] >= -1e-9).all()  # joint never below sequential
    assert not tables["budget_grid"]["block_moves"].any() and tables["block_grid"]["block_moves"].all()


def test_search_log_has_one_row_per_restart(run):
    _, tables = run
    log = tables["search_log"]
    assert len(log) == 4 * 2  # 4 runs x 2 restarts
    assert (log["infeasible"] <= log["tried"]).all()
    assert (log["last_improvement"] <= log["iterations"]).all()
    assert set(log.loc[log["restart"] == 0, "start"]) == {"sequential"}


def test_ties_table_lists_every_non_improving_run(run):
    _, tables = run
    losses = tables["ties_and_losses"]
    expected = sum(int((tables[k]["obj_gain"] < 0.01).sum()) for k in ("budget_grid", "block_grid"))
    assert len(losses) == expected
    assert set(losses["result"]) <= {"tie", "loss"}
    assert "EVERY run" in report_v4(tables)
