"""Version 6 evaluation: the verdict judges TOTAL waiting (incl. idle before lunch), and every
tie or loss gets the wait-weight break-even.

    python scripts/evaluate_v6.py          # main + every single-rule setting (several minutes)

Everything goes to data/results/v6/. v1 (data/results/) and v2-v5 are only READ.
No plan, objective, weight or baseline changes: the same runs as v5 parts 1 and 2, with
config.VERDICT_USE_TOTAL_WAIT on. Fixed before any v6 run.

    results.csv, summary.csv, ...  main evaluation, all v5 rules on (as v5 part 1)
    ablation/<setting>/            each rule on alone, plus "early start" (as v5 part 2)
    ablation.csv                   every run of every setting (all rules on last)
    reproduction.csv               every run next to v5 (same plans expected; runtime not compared)
    verdict_changes.csv            per run: verdict with wait_min (v5 rule) and with total_wait_min (v6)
    verdict_change_counts.csv      per setting: verdict counts under both rules, and how many changed
    ablation_summary.csv           joint vs sequential per setting, new verdict rule
    ties_and_losses.csv            EVERY run where joint ties or loses (new verdict rule), with the
                                   wait-weight break-even

Break-even: the objective is linear in the wait weight w, so for two FIXED plans
    joint_obj(w) - seq_obj(w) = (joint_obj - seq_obj at the run's w) - (w' - w) x (joint_wait - seq_wait) h
and sequential scores higher on one side of the w' where that is 0. The joint plan is held
fixed: under another wait weight the optimizer might find a different plan, so the break-even
says how robust THIS comparison is, not what joint would do at that weight.

All inputs are mock data, travel times are APPROX haversine estimates, every v5 value is APPROX.
"""

import argparse
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # allow "python scripts/evaluate_v6.py"

from scripts.evaluate import JOINT, SEQ, report, run_evaluation, summarise  # noqa: E402
from scripts.evaluate_v3 import _one_setting_summary, overridden, ties_and_losses  # noqa: E402
from scripts.evaluate_v5 import ABLATION, ALL_LABEL, ALL_ON, _row_v5, _same, run_ablation  # noqa: E402
from src import config  # noqa: E402
from src.objective import plan_totals  # noqa: E402
from src.scenarios import build_scenarios  # noqa: E402

RESULTS_DIR = config.DATA_DIR / "results" / "v6"
V5_DIR = config.DATA_DIR / "results" / "v5"
PROTECTED = [config.DATA_DIR / "results", *(config.DATA_DIR / "results" / v for v in ("v2", "v3", "v4", "v5"))]
VERDICTS = ("better", "same", "mixed", "worse")


def _row_v6(scenario, weight_name, method, result, objective, runtime_s) -> dict:
    """The v5 row plus the waiting exactly as the objective counts it (2 decimals, not 1)."""
    row = _row_v5(scenario, weight_name, method, result, objective, runtime_s)
    it = result.itinerary
    row["objective_wait_min"] = plan_totals(it.days, it.unscheduled, result.budget_report)["wait_min"]
    return row


# ---------- Reproduction against v5 ----------

def compare_runs(new: pd.DataFrame, old: pd.DataFrame, keys: Sequence[str]) -> pd.DataFrame:
    """Every run of old next to new, on every column of old except runtime_s."""
    columns = [c for c in old.columns if c not in (*keys, "runtime_s")]
    new_i, old_i = new.set_index(list(keys)), old.set_index(list(keys))
    rows = []
    for key in old_i.index.union(new_i.index):
        if key not in new_i.index or key not in old_i.index:
            rows.append({**dict(zip(keys, key)), "matches": False, "differing_columns": "missing run"})
            continue
        diff = [c for c in columns if not _same(old_i.loc[key, c], new_i.loc[key, c])]
        rows.append({**dict(zip(keys, key)), "matches": not diff, "differing_columns": ", ".join(diff)})
    return pd.DataFrame(rows)


# ---------- Verdict changes ----------

def verdict_changes(all_runs: pd.DataFrame) -> pd.DataFrame:
    """Per setting x scenario x weights: the verdict under the v5 rule and under the v6 rule."""
    out = []
    for setting, g in all_runs.groupby("setting", sort=False):
        with overridden(VERDICT_USE_TOTAL_WAIT=False):
            old = summarise(g)
        with overridden(VERDICT_USE_TOTAL_WAIT=True):
            new = summarise(g)
        old, new = (t[t["scenario_id"] != "MEAN"] for t in (old, new))
        merged = new[["scenario_id", "weights", "seq_wait_min", "joint_wait_min", "seq_total_wait_min",
                      "joint_total_wait_min", "verdict"]].rename(columns={"verdict": "verdict_total_wait"})
        merged.insert(2, "verdict_v5_rule", old["verdict"].values)
        merged.insert(0, "setting", setting)
        merged["changed"] = merged["verdict_v5_rule"] != merged["verdict_total_wait"]
        out.append(merged)
    return pd.concat(out, ignore_index=True)


def verdict_change_counts(changes: pd.DataFrame) -> pd.DataFrame:
    """Per setting (and in total): counts under both rules and every verdict that moved."""
    rows = []
    for setting, g in [*changes.groupby("setting", sort=False), ("TOTAL", changes)]:
        old, new = g["verdict_v5_rule"].value_counts(), g["verdict_total_wait"].value_counts()
        moved = g[g["changed"]].groupby(["verdict_v5_rule", "verdict_total_wait"], sort=False).size()
        rows.append({"setting": setting, "runs": len(g),
                     **{f"{v}_v5_rule": int(old.get(v, 0)) for v in VERDICTS},
                     **{f"{v}_total_wait": int(new.get(v, 0)) for v in VERDICTS},
                     "changed": int(g["changed"].sum()),
                     "changes": "; ".join(f"{a}->{b}: {n}" for (a, b), n in moved.items()) or "none"})
    return pd.DataFrame(rows)


# ---------- Wait-weight break-even ----------

def wait_breakeven(seq_obj: float, joint_obj: float, seq_wait_min: float, joint_wait_min: float,
                   wait_weight: float) -> tuple[float, str]:
    """(w', when sequential scores higher than joint), for these two fixed plans.

    Returns NaN when the plans wait equally long (the wait weight cannot change their order).
    """
    d_wait_h = (joint_wait_min - seq_wait_min) / config.OBJECTIVE_TIME_SCALE_MIN
    if abs(d_wait_h) < 1e-9:
        return float("nan"), "never: same waiting"
    w = round(wait_weight + (joint_obj - seq_obj) / d_wait_h, 3)
    if d_wait_h < 0:  # joint waits less, so a smaller wait weight helps sequential
        return w, f"wait weight < {w}" if w > 0 else "never: needs a negative wait weight"
    return w, f"wait weight > {w}"


def add_wait_breakeven(losses: pd.DataFrame, all_runs: pd.DataFrame,
                       weight_settings: Mapping[str, Mapping[str, float]]) -> pd.DataFrame:
    """losses (from ties_and_losses, setting = the all_runs setting) plus the break-even columns."""
    if not len(losses):
        return losses
    runs = all_runs.set_index(["setting", "scenario_id", "weights", "method"])
    extra = []
    for _, r in losses.iterrows():
        s, j = (runs.loc[(r["setting"], r["scenario_id"], r["weights"], m)] for m in (SEQ, JOINT))
        w = weight_settings[r["weights"]]["wait"]
        value, when = wait_breakeven(s["objective_score"], j["objective_score"],
                                     s["objective_wait_min"], j["objective_wait_min"], w)
        extra.append({"wait_weight": w, "seq_wait_obj_min": s["objective_wait_min"],
                      "joint_wait_obj_min": j["objective_wait_min"], "wait_breakeven": value,
                      "seq_scores_higher_if": when})
    return pd.concat([losses.reset_index(drop=True), pd.DataFrame(extra)], axis=1)


# ---------- Run everything ----------

def _check_out_dir(out_dir: Path):
    if Path(out_dir).resolve() in {p.resolve() for p in PROTECTED}:
        raise ValueError(f"refusing to write into the v1-v5 folder {out_dir}")


def run_v6(out_dir: Path = RESULTS_DIR, cache_dir: Path = config.CACHE_DIR,
           max_iterations: int = config.JOINT_MAX_ITERATIONS,
           scenario_ids: Sequence[str] | None = None,
           weight_settings: Mapping[str, Mapping[str, float]] = config.EVALUATION_WEIGHT_SETTINGS,
           ablation=ABLATION, v5_dir: Path = V5_DIR) -> dict:
    out_dir, cache_dir, v5_dir = Path(out_dir), Path(cache_dir), Path(v5_dir)
    _check_out_dir(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    scenarios = build_scenarios()
    if scenario_ids:
        scenarios = [s for s in scenarios if s.id in set(scenario_ids)]
    descriptions = {s.id: s.description for s in scenarios}
    tables: dict = {}

    with overridden(VERDICT_USE_TOTAL_WAIT=True):
        print("Main evaluation, all v5 rules on", flush=True)
        with overridden(**ALL_ON):
            main = run_evaluation(scenarios, weight_settings, out_dir=out_dir, cache_dir=cache_dir,
                                  max_iterations=max_iterations, row_fn=_row_v6)
            tables["main_report"] = report(main, scenarios)
        tables.update(main)
        print("Single-rule settings", flush=True)
        abl = run_ablation(scenarios, weight_settings, max_iterations, cache_dir, out_dir, ablation, row_fn=_row_v6)
        all_runs = pd.concat([abl, main["results"].assign(setting=ALL_LABEL)], ignore_index=True)
        tables["ablation"] = all_runs
        tables["ablation_summary"] = pd.DataFrame([{"setting": label, **_one_setting_summary(g)}
                                                   for label, g in all_runs.groupby("setting", sort=False)])
        losses = pd.concat([ties_and_losses(g, "v6", label, descriptions)
                            for label, g in all_runs.groupby("setting", sort=False)], ignore_index=True)
    tables["ties_and_losses"] = add_wait_breakeven(losses, all_runs, weight_settings)
    tables["verdict_changes"] = verdict_changes(all_runs)
    tables["verdict_change_counts"] = verdict_change_counts(tables["verdict_changes"])

    repro = []
    if (v5_dir / "results.csv").exists():
        repro.append(compare_runs(main["results"], pd.read_csv(v5_dir / "results.csv"),
                                  ["scenario_id", "weights", "method"]).assign(setting=ALL_LABEL))
    if (v5_dir / "ablation.csv").exists():
        old = pd.read_csv(v5_dir / "ablation.csv")
        old = old[old["setting"].isin(set(abl["setting"]))]  # v5's all-off rows were not rerun
        repro.append(compare_runs(abl, old, ["setting", "scenario_id", "weights", "method"]))
    tables["reproduction"] = pd.concat(repro, ignore_index=True) if repro else pd.DataFrame()

    for key in ("ablation", "ablation_summary", "ties_and_losses", "verdict_changes", "verdict_change_counts",
                "reproduction"):
        tables[key].to_csv(out_dir / f"{key}.csv", index=False)
    return tables


# ---------- Report ----------

def report_v6(tables: Mapping) -> str:
    lines = ["#" * 20 + " Main evaluation, all v5 rules on, verdict on total waiting " + "#" * 20,
             tables["main_report"], ""]
    r = tables["reproduction"]
    lines += ["=== Reproduction: same runs as v5 (every column except runtime_s) ===",
              f"{int(r['matches'].sum())} of {len(r)} runs identical to v5" if len(r) else "v5 not found: not compared"]
    if len(r) and not r["matches"].all():
        lines.append(r[~r["matches"]].to_string(index=False))
    changes = tables["verdict_changes"]
    lines += ["", "=== Verdict counts: v5 rule (wait_min) vs v6 rule (total_wait_min) ===",
              tables["verdict_change_counts"].to_string(index=False), "",
              "=== Every run whose verdict changed ===",
              changes[changes["changed"]].to_string(index=False) if changes["changed"].any() else "none", "",
              "=== Joint vs sequential per setting (v6 verdict rule) ===",
              tables["ablation_summary"].to_string(index=False), ""]
    losses = tables["ties_and_losses"]
    lines.append("#" * 20 + " EVERY run where joint ties or loses (v6 verdict rule), with the break-even " + "#" * 20)
    if not len(losses):
        lines.append("none")
    for setting, g in losses.groupby("setting", sort=False) if len(losses) else []:
        lines += [f"--- {setting}: {len(g)} runs ---",
                  g.drop(columns=["part", "setting", "description"]).to_string(index=False)]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--iterations", type=int, default=config.JOINT_MAX_ITERATIONS)
    parser.add_argument("--out-dir", type=Path, default=RESULTS_DIR)
    args = parser.parse_args(argv)

    start = time.perf_counter()
    tables = run_v6(out_dir=args.out_dir, max_iterations=args.iterations)
    pd.set_option("display.width", 260)
    pd.set_option("display.max_columns", 60)
    pd.set_option("display.max_rows", 1000)
    print(report_v6(tables))
    print(f"\nWritten to {args.out_dir} in {time.perf_counter() - start:.0f} s")


if __name__ == "__main__":
    main()
