"""Version 4 evaluation: why does joint tie sequential at 30 and 50 places?

    python scripts/evaluate_v4.py                    # everything (about half an hour)
    python scripts/evaluate_v4.py --parts grid       # only part 1 (about 15 minutes)

Everything goes to data/results/v4/. v1, v2 and v3 files are never written.

    1. Budget grid: L30-M, L30-T, L50-M, L50-T rerun with the search budget (changes
       per restart) at 1x / 2x / 5x / 10x config.JOINT_MAX_ITERATIONS, each with 5 and
       15 restarts. 1x with 5 restarts is the v3 setting.
       budget_grid.csv   one row per trip x budget x restarts: score, places, run time,
                         and a summary of the search log
       search_log.csv    one row per restart of every run: changes tried / infeasible /
                         accepted / improving, the iteration of the last improvement,
                         and the same counts per change kind
       Result of part 1: more budget does NOT remove the ties at 50 places (L50-M ties
       at every setting), so no budget-scaling rule was added. See part 2 instead.
    2. Block move: the same grid with the new "block" change switched on
       (config.JOINT_USE_BLOCK_MOVES / JOINT_BLOCK_MAX_LEN). Objective and baselines unchanged.
       block_grid.csv, block_search_log.csv   same columns as part 1
       block_vs_grid.csv                      part 1 and part 2 side by side, per setting
    3. ties_and_losses.csv   EVERY run above where joint ties or loses against sequential.

All inputs are mock (or SYNTHETIC) data and the travel matrix is the APPROX haversine estimate.
"""

import argparse
import sys
import time
from collections.abc import Sequence
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # allow "python scripts/evaluate_v4.py"

from scripts.evaluate import EPS  # noqa: E402
from src import config  # noqa: E402
from src.joint import JointResult, optimize_joint  # noqa: E402
from src.scenarios import Scenario, build_scalability_scenarios  # noqa: E402

RESULTS_DIR = config.DATA_DIR / "results" / "v4"
PROTECTED = [config.DATA_DIR / "results", *(config.DATA_DIR / "results" / v for v in ("v2", "v3"))]

# Fixed before any v4 run (from the task): the four trips where v3 joint tied or nearly tied.
GRID_SCENARIOS = ("L30-M", "L30-T", "L50-M", "L50-T")
GRID_MULTIPLIERS = (1, 2, 5, 10)  # x config.JOINT_MAX_ITERATIONS; 1 = the v3 setting
GRID_RESTARTS = (5, 15)
LATE_SHARE = 0.9  # an improvement after 90% of the budget counts as "still improving at the end"
KINDS = ("swap", "move", "drop", "insert", "block")


# ---------- One run and its search log ----------

def _log_rows(sc: Scenario, label: str, r: JointResult) -> list[dict]:
    """One row per restart, with the counters from RestartStats."""
    rows = []
    for st in r.stats:
        row = {"scenario_id": sc.id, "run": label, "restart": st.restart,
               "start": "sequential" if st.restart == 0 else "random",
               "iterations": st.iterations, "start_score": st.start_score, "best_score": st.best_score,
               "tried": st.tried, "infeasible": st.infeasible,
               "infeasible_pct": round(100 * st.infeasible / st.tried, 1) if st.tried else 0.0,
               "accepted": st.accepted, "accepted_worse": st.accepted_worse,
               "improvements": st.improvements, "last_improvement": st.last_improvement,
               "last_improvement_pct": round(100 * st.last_improvement / st.iterations, 1),
               "won": st.restart == r.restart}
        for kind in KINDS:
            t, f, a, i = st.by_kind.get(kind, [0, 0, 0, 0])
            row.update({f"{kind}_tried": t, f"{kind}_feasible": f, f"{kind}_accepted": a,
                        f"{kind}_improved": i})
        rows.append(row)
    return rows


def _run_row(sc: Scenario, label: str, r: JointResult, runtime_s: float, **extra) -> dict:
    """Score, places, time, and what the search log says about this run."""
    seq = r.baseline.score.total
    st = r.stats
    random_best = max((s.best_score for s in st if s.restart > 0), default=float("nan"))
    late = [s for s in st if s.last_improvement > LATE_SHARE * s.iterations]
    return {
        "scenario_id": sc.id, "run": label, "places": len(sc.destinations), "days": sc.trip.num_days,
        **extra,
        "seq_obj": seq, "joint_obj": r.score.total, "obj_gain": round(r.score.total - seq, 4),
        "joint_improves_obj": "yes" if r.score.total - seq >= EPS else "no (tie)",
        "seq_places": sum(len(d.stops) for d in r.baseline.itinerary.days),
        "joint_places": sum(len(d.stops) for d in r.itinerary.days),
        "runtime_s": round(runtime_s, 2), "winning_restart": r.restart,
        "tried": sum(s.tried for s in st), "infeasible": sum(s.infeasible for s in st),
        "accepted": sum(s.accepted for s in st), "improvements": sum(s.improvements for s in st),
        # restart 0 starts from the sequential plan: did it ever beat it, and when last?
        "r0_improvements": st[0].improvements, "r0_last_improvement": st[0].last_improvement,
        "best_random_restart_obj": random_best,
        "random_gap_to_seq": round(random_best - seq, 4),
        "restarts_improving_late": len(late),
        "random_last_impr_pct_mean": round(sum(100 * s.last_improvement / s.iterations
                                               for s in st if s.restart > 0)
                                           / max(1, len(st) - 1), 1),
    }


def _timed_joint(sc: Scenario, **kwargs) -> tuple[JointResult, float]:
    start = time.perf_counter()
    r = optimize_joint(sc.destinations, sc.trip, **kwargs)
    return r, time.perf_counter() - start


# ---------- 1. Budget grid ----------

def run_budget_grid(scenarios: Sequence[Scenario], multipliers=GRID_MULTIPLIERS, restarts=GRID_RESTARTS,
                    base_iterations: int = config.JOINT_MAX_ITERATIONS, cache_dir: Path = config.CACHE_DIR,
                    block_moves: bool = False) -> tuple[pd.DataFrame, pd.DataFrame]:
    runs, log = [], []
    for sc in scenarios:
        for m in multipliers:
            for n in restarts:
                label = f"{m}x, {n} restarts" + (", block" if block_moves else "")
                r, t = _timed_joint(sc, max_iterations=base_iterations * m, restarts=n,
                                    seed=config.JOINT_SEED, cache_dir=cache_dir, block_moves=block_moves)
                runs.append(_run_row(sc, label, r, t, multiplier=m, iterations=base_iterations * m,
                                     restarts=n, block_moves=block_moves))
                log += _log_rows(sc, label, r)
                print(f"  {sc.id} {label}: joint {r.score.total:.2f} vs seq {r.baseline.score.total:.2f} "
                      f"({t:.1f} s)", flush=True)
    return pd.DataFrame(runs), pd.DataFrame(log)


# ---------- 2. Block move vs part 1 ----------

def block_vs_grid(grid: pd.DataFrame, block: pd.DataFrame) -> pd.DataFrame:
    """Same trip, budget and restarts, without and with the block move."""
    keys = ["scenario_id", "multiplier", "restarts"]
    cols = ["joint_obj", "obj_gain", "joint_places", "runtime_s", "r0_improvements", "best_random_restart_obj"]
    out = grid[[*keys, "seq_obj", *cols]].merge(block[[*keys, *cols]], on=keys, suffixes=("", "_block"))
    out["block_minus_grid"] = (out["joint_obj_block"] - out["joint_obj"]).round(4)
    out["block_effect"] = ["better" if d >= EPS else "worse" if d <= -EPS else "same"
                           for d in out["block_minus_grid"]]
    return out


# ---------- 3. Ties and losses ----------

def ties_and_losses(runs: pd.DataFrame, part: str) -> pd.DataFrame:
    """Every run where joint does not beat sequential by at least EPS (ties AND losses)."""
    bad = runs[runs["obj_gain"] < EPS]
    out = bad[["scenario_id", "run", "seq_obj", "joint_obj", "obj_gain", "seq_places", "joint_places"]].copy()
    out.insert(0, "part", part)
    out["result"] = ["loss" if g <= -EPS else "tie" for g in bad["obj_gain"]]
    return out


# ---------- Run everything ----------

def _check_out_dir(out_dir: Path):
    if Path(out_dir).resolve() in {p.resolve() for p in PROTECTED}:
        raise ValueError(f"refusing to write into the v1/v2/v3 folder {out_dir}")


def run_v4(out_dir: Path = RESULTS_DIR, cache_dir: Path = config.CACHE_DIR,
           parts: Sequence[str] = ("grid", "block"),
           grid_scenarios: Sequence[Scenario] | None = None,
           multipliers=GRID_MULTIPLIERS, restarts=GRID_RESTARTS,
           base_iterations: int = config.JOINT_MAX_ITERATIONS) -> dict[str, pd.DataFrame]:
    out_dir = Path(out_dir)
    _check_out_dir(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if grid_scenarios is None:
        grid_scenarios = [s for s in build_scalability_scenarios() if s.id in GRID_SCENARIOS]

    tables, losses = {}, []
    if "grid" in parts:
        print("Part 1: budget grid", flush=True)
        grid, log = run_budget_grid(grid_scenarios, multipliers, restarts, base_iterations, cache_dir)
        tables.update(budget_grid=grid, search_log=log)
        losses.append(ties_and_losses(grid, "budget grid"))
    if "block" in parts:
        print("Part 2: budget grid with the block move", flush=True)
        block, block_log = run_budget_grid(grid_scenarios, multipliers, restarts, base_iterations, cache_dir,
                                           block_moves=True)
        tables.update(block_grid=block, block_search_log=block_log)
        if "budget_grid" in tables:
            tables["block_vs_grid"] = block_vs_grid(tables["budget_grid"], block)
        losses.append(ties_and_losses(block, "block move"))
    tables["ties_and_losses"] = pd.concat(losses, ignore_index=True) if losses else pd.DataFrame()
    for name, table in tables.items():
        table.to_csv(out_dir / f"{name}.csv", index=False)
    return tables


GRID_COLUMNS = ["scenario_id", "multiplier", "restarts", "seq_obj", "joint_obj", "obj_gain", "seq_places",
                "joint_places", "runtime_s", "winning_restart", "tried", "infeasible", "accepted",
                "r0_improvements", "r0_last_improvement", "best_random_restart_obj", "random_gap_to_seq",
                "restarts_improving_late", "random_last_impr_pct_mean"]
BLOCK_COLUMNS = ["scenario_id", "multiplier", "restarts", "seq_obj", "joint_obj", "joint_obj_block",
                 "block_minus_grid", "block_effect", "obj_gain_block", "joint_places", "joint_places_block",
                 "runtime_s", "runtime_s_block", "r0_improvements", "r0_improvements_block",
                 "best_random_restart_obj", "best_random_restart_obj_block"]


def report_v4(tables) -> str:
    lines = []
    if "budget_grid" in tables:
        lines += ["=== 1. Budget grid (multiplier x config.JOINT_MAX_ITERATIONS per restart) ===",
                  tables["budget_grid"][GRID_COLUMNS].to_string(index=False), ""]
    if "block_grid" in tables:
        lines += ["=== 2. Same grid with the block move ===",
                  tables["block_grid"][GRID_COLUMNS].to_string(index=False), ""]
    if "block_vs_grid" in tables:
        c = tables["block_vs_grid"]
        lines += ["=== 2b. Block move vs part 1 (same trip, budget, restarts, seed) ===",
                  c[BLOCK_COLUMNS].to_string(index=False),
                  "block move effect: " + ", ".join(f"{k} {v}" for k, v in c["block_effect"].value_counts().items()),
                  ""]
    losses = tables["ties_and_losses"]
    lines += ["=== 3. EVERY run where joint ties or loses ===",
              losses.to_string(index=False) if len(losses) else "none"]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--parts", nargs="+", default=["grid", "block"], choices=["grid", "block"])
    parser.add_argument("--out-dir", type=Path, default=RESULTS_DIR)
    args = parser.parse_args(argv)

    start = time.perf_counter()
    tables = run_v4(out_dir=args.out_dir, parts=args.parts)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 40)
    pd.set_option("display.max_rows", 500)
    print(report_v4(tables))
    print(f"\nWritten to {args.out_dir} in {time.perf_counter() - start:.0f} s")


if __name__ == "__main__":
    main()
