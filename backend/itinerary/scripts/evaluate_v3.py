"""Version 3 evaluation: conflict penalty, scalability test and sensitivity check.

    python scripts/evaluate_v3.py                    # everything (a few minutes)
    python scripts/evaluate_v3.py --iterations 300   # quicker smoke run

Everything goes to data/results/v3/. Version 1 (data/results/) and version 2
(data/results/v2/) files are only READ, never written.

    1. Main evaluation (scripts/evaluate.py) again, now that the objective has the
       opening-hour CONFLICT_PENALTY: results.csv, summary.csv, method_means*.csv,
       exact_gap.csv and the charts.
       objective_check.csv     v2 vs v3 objective of every run. Only naive plans with
                               conflicts may change; sequential, joint and exact must not.
    2. Scalability: 15 real places + seeded SYNTHETIC ones, 20 / 30 / 50 places
       (src/scenarios.build_scalability_scenarios). Sequential and joint only
       (the exact benchmark cannot handle more than config.EXACT_MAX_PLACES places).
       scalability.csv          one row per trip x method
       scalability_summary.csv  sequential vs joint per trip
    3. Sensitivity: a fixed subset of scenarios rerun with COVERAGE_PENALTY 10 / 20 / 40
       and annealing temperature ranges 0.5->0.0025 / 2->0.01 / 8->0.04 (one at a time).
       sensitivity.csv          one row per setting x scenario x weight setting x method
       sensitivity_summary.csv  one row per setting, and whether the conclusions change
    4. ties_and_losses.csv      EVERY run, in all three parts, where joint ties or loses.

All inputs are mock (or SYNTHETIC) data and the travel matrix is the APPROX haversine estimate.
"""

import argparse
import sys
import time
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # allow "python scripts/evaluate_v3.py"

from scripts.evaluate import (EPS, JOINT, NAIVE, SEQ, _row, _timed, evaluate_scenario,  # noqa: E402
                              report, run_evaluation, summarise)
from src import config  # noqa: E402
from src.joint import optimize_joint  # noqa: E402
from src.metrics import travel_time_reduction_pct  # noqa: E402
from src.pipeline import run_sequential  # noqa: E402
from src.scenarios import Scenario, build_scalability_scenarios, build_scenarios  # noqa: E402
from src.synthetic import is_synthetic  # noqa: E402

RESULTS_DIR = config.DATA_DIR / "results" / "v3"
V2_RESULTS = config.DATA_DIR / "results" / "v2" / "results.csv"

# Fixed before any v3 run: a mix of ordinary (S02, S05), tight-budget (S07, S10),
# early-closing (S12) and tight + early-closing (S14) trips.
SENSITIVITY_SCENARIOS = ("S02", "S05", "S07", "S10", "S12", "S14")
DEFAULT_SETTING = "default (coverage 20, T 2->0.01)"
# (label, parameter, config overrides). Each parameter is changed on its own; the rest stay default.
SENSITIVITY_SETTINGS = [
    (DEFAULT_SETTING, "-", {}),
    ("coverage 10", "COVERAGE_PENALTY", {"COVERAGE_PENALTY": 10.0}),
    ("coverage 40", "COVERAGE_PENALTY", {"COVERAGE_PENALTY": 40.0}),
    ("T 0.5->0.0025", "anneal temperature", {"JOINT_ANNEAL_START_TEMP": 0.5, "JOINT_ANNEAL_END_TEMP": 0.0025}),
    ("T 8->0.04", "anneal temperature", {"JOINT_ANNEAL_START_TEMP": 8.0, "JOINT_ANNEAL_END_TEMP": 0.04}),
]


@contextmanager
def overridden(**values):
    """Temporarily change config constants (the modules read them at call time), then restore."""
    unknown = [k for k in values if not hasattr(config, k)]
    if unknown:
        raise AttributeError(f"no such config constants: {unknown}")
    old = {k: getattr(config, k) for k in values}
    try:
        for k, v in values.items():
            setattr(config, k, v)
        yield
    finally:
        for k, v in old.items():
            setattr(config, k, v)


# ---------- 1. v2 vs v3 objective ----------

def objective_check(v3: pd.DataFrame, v2_path: Path = V2_RESULTS) -> pd.DataFrame:
    """Objective of every run in v2 and v3, side by side. 'expected' says whether the change
    is the one the penalty should cause: none without conflicts, -CONFLICT_PENALTY per bad stop."""
    if not Path(v2_path).exists():
        return pd.DataFrame()
    keys = ["scenario_id", "weights", "method"]
    v2 = pd.read_csv(v2_path)[[*keys, "objective_score", "conflicts"]]
    out = v2.merge(v3[[*keys, "objective_score"]], on=keys, suffixes=("_v2", "_v3"))
    out["diff"] = (out["objective_score_v3"] - out["objective_score_v2"]).round(4)
    out["changed"] = out["diff"].abs() >= EPS
    # the plans themselves did not change, so a run may only change if it has conflicts
    out["expected"] = out["changed"] == (out["conflicts"] > 0)
    return out


def objective_check_summary(check: pd.DataFrame) -> pd.DataFrame:
    g = check.groupby("method", sort=False)
    return pd.DataFrame({"runs": g.size(), "runs_with_conflicts": g["conflicts"].apply(lambda c: int((c > 0).sum())),
                         "runs_changed": g["changed"].sum(), "max_abs_diff": g["diff"].apply(lambda d: d.abs().max()),
                         "all_as_expected": g["expected"].all()}).reset_index()


# ---------- 2. Scalability ----------

def run_scalability(scenarios: Sequence[Scenario], max_iterations: int, cache_dir: Path) -> pd.DataFrame:
    """Sequential and joint (default weights) on each larger trip."""
    rows = []
    for sc in scenarios:
        extra = {"places_in_input": len(sc.destinations),
                 "synthetic_places": sum(is_synthetic(d) for d in sc.destinations),
                 "num_days": sc.trip.num_days}
        seq, t = _timed(run_sequential, sc.destinations, sc.trip, cache_dir=cache_dir)
        rows.append({**_row(sc, "default", SEQ, seq, seq.score.total, t), **extra})
        jnt, t = _timed(optimize_joint, sc.destinations, sc.trip, weights=config.OBJECTIVE_WEIGHTS,
                        max_iterations=max_iterations, seed=config.JOINT_SEED, cache_dir=cache_dir)
        rows.append({**_row(sc, "default", JOINT, jnt, jnt.score.total, t), **extra})
    return pd.DataFrame(rows)


def scalability_summary(results: pd.DataFrame) -> pd.DataFrame:
    verdicts = summarise(results).set_index(["scenario_id", "weights"])["verdict"]
    rows = []
    for sid, g in results.groupby("scenario_id", sort=False):
        s, j = g[g["method"] == SEQ].iloc[0], g[g["method"] == JOINT].iloc[0]
        gain = round(j["objective_score"] - s["objective_score"], 4)
        rows.append({
            "scenario_id": sid, "places": s["places_in_input"], "synthetic": s["synthetic_places"],
            "days": s["num_days"], "budget": s["tags"].split(",")[0],
            "seq_runtime_s": s["runtime_s"], "joint_runtime_s": j["runtime_s"],
            "seq_places_sched": s["places_scheduled"], "joint_places_sched": j["places_scheduled"],
            "seq_score_coll": s["score_collected"], "joint_score_coll": j["score_collected"],
            "travel_reduction_pct": travel_time_reduction_pct(s["travel_min"], j["travel_min"]),
            "seq_in_budget": s["within_budget"], "joint_in_budget": j["within_budget"],
            "seq_obj": s["objective_score"], "joint_obj": j["objective_score"], "obj_gain": gain,
            "joint_improves_obj": "yes" if gain >= EPS else "no (tie)",
            "verdict": verdicts[(sid, "default")],
        })
    return pd.DataFrame(rows)


# ---------- 3. Sensitivity ----------

def run_sensitivity(scenarios: Sequence[Scenario], weight_settings: Mapping[str, Mapping[str, float]],
                    max_iterations: int, cache_dir: Path, settings=SENSITIVITY_SETTINGS) -> pd.DataFrame:
    """naive / sequential / joint rows for every setting (exact is not needed here)."""
    rows = []
    for label, parameter, overrides in settings:
        with overridden(**overrides):
            for sc in scenarios:
                for row in evaluate_scenario(sc, weight_settings, max_iterations, cache_dir, run_exact=False):
                    rows.append({"setting": label, "parameter": parameter, **row})
    return pd.DataFrame(rows)


# Statements that make up "the conclusion" of the comparison. The check reports, for every
# setting, which of them hold, and whether that is the same as under the default setting.
CONCLUSIONS = {
    "joint_improves_obj_in_most_runs": lambda r: r["obj_improved"] > r["runs"] / 2,
    "no_worse_verdicts": lambda r: r["worse"] == 0,
    "joint_adherence_not_lower": lambda r: r["joint_adherence"] >= r["seq_adherence"],
    "joint_collects_more_score": lambda r: r["mean_diff_score_coll"] > 0,
    "joint_less_total_travel": lambda r: r["travel_reduction_of_totals_pct"] > 0,
    "naive_never_beats_joint_obj": lambda r: r["naive_obj_above_joint"] == 0,
}


def _one_setting_summary(results: pd.DataFrame) -> dict:
    per = summarise(results)
    per = per[per["scenario_id"] != "MEAN"]
    obj = results.pivot_table(index=["scenario_id", "weights"], columns="method", values="objective_score")
    seq_travel = results[results["method"] == SEQ]["travel_min"].sum()
    joint_travel = results[results["method"] == JOINT]["travel_min"].sum()
    counts = per["verdict"].value_counts()
    return {
        "runs": len(per),
        **{v: int(counts.get(v, 0)) for v in ("better", "same", "mixed", "worse")},
        "obj_improved": int((obj[JOINT] - obj[SEQ] >= EPS).sum()),
        "obj_ties": int(((obj[JOINT] - obj[SEQ]).abs() < EPS).sum()),
        "mean_obj_gain": round((obj[JOINT] - obj[SEQ]).mean(), 3),
        "mean_diff_score_coll": round(per["diff_score_collected"].mean(), 3),
        "mean_diff_places": round(per["diff_places_scheduled"].mean(), 3),
        "travel_reduction_of_totals_pct": travel_time_reduction_pct(seq_travel, joint_travel),
        "seq_adherence": round(per["seq_within_budget"].mean(), 3),
        "joint_adherence": round(per["joint_within_budget"].mean(), 3),
        "naive_obj_above_joint": int((obj[NAIVE] > obj[JOINT] + EPS).sum()),
    }


def sensitivity_summary(results: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (label, parameter), g in results.groupby(["setting", "parameter"], sort=False):
        row = {"setting": label, "parameter": parameter, **_one_setting_summary(g)}
        row.update({name: test(row) for name, test in CONCLUSIONS.items()})
        rows.append(row)
    out = pd.DataFrame(rows)
    default = out[out["setting"] == DEFAULT_SETTING].iloc[0]
    out["changed_conclusions"] = [
        ", ".join(n for n in CONCLUSIONS if row[n] != default[n]) or "none" for _, row in out.iterrows()]
    out["conclusions_same"] = out["changed_conclusions"] == "none"
    return out


# ---------- 4. Every run where joint ties or loses ----------

def ties_and_losses(results: pd.DataFrame, part: str, setting: str = "-",
                    descriptions: Mapping[str, str] | None = None) -> pd.DataFrame:
    """Runs where the verdict is not 'better', the objective did not improve, or naive scores higher."""
    per = summarise(results)
    per = per[per["scenario_id"] != "MEAN"].set_index(["scenario_id", "weights"])
    obj = results.pivot_table(index=["scenario_id", "weights"], columns="method", values="objective_score")
    rows = []
    for key, r in per.iterrows():
        tie = abs(obj.loc[key, JOINT] - obj.loc[key, SEQ]) < EPS
        naive_above = NAIVE in obj.columns and obj.loc[key, NAIVE] > obj.loc[key, JOINT] + EPS
        if r["verdict"] == "better" and not tie and not naive_above:
            continue
        rows.append({"part": part, "setting": setting, "scenario_id": key[0], "weights": key[1],
                     "verdict": r["verdict"], "objective_tie": "yes" if tie else "no",
                     "naive_obj_above_joint": "yes" if naive_above else "no",
                     "seq_obj": obj.loc[key, SEQ], "joint_obj": obj.loc[key, JOINT],
                     "description": (descriptions or {}).get(key[0], "")})
    return pd.DataFrame(rows)


# ---------- Run everything ----------

def run_v3(out_dir: Path = RESULTS_DIR, cache_dir: Path = config.CACHE_DIR,
           max_iterations: int = config.JOINT_MAX_ITERATIONS,
           scenario_ids: Sequence[str] | None = None,
           scale_scenarios: Sequence[Scenario] | None = None,
           sensitivity_ids: Sequence[str] = SENSITIVITY_SCENARIOS,
           weight_settings: Mapping[str, Mapping[str, float]] = config.EVALUATION_WEIGHT_SETTINGS,
           v2_path: Path = V2_RESULTS) -> dict[str, pd.DataFrame]:
    """All three parts. Writes every table to out_dir and returns them."""
    out_dir = Path(out_dir)
    if out_dir.resolve() in {(config.DATA_DIR / "results").resolve(), V2_RESULTS.parent.resolve()}:
        raise ValueError(f"refusing to write into the v1/v2 folder {out_dir}")
    scenarios = build_scenarios()
    if scenario_ids:
        scenarios = [s for s in scenarios if s.id in set(scenario_ids)]
    descriptions = {s.id: s.description for s in scenarios}

    main = run_evaluation(scenarios, weight_settings, out_dir=out_dir, cache_dir=cache_dir,
                          max_iterations=max_iterations)
    check = objective_check(main["results"], v2_path)

    scale_scenarios = build_scalability_scenarios() if scale_scenarios is None else scale_scenarios
    scale = run_scalability(scale_scenarios, max_iterations, cache_dir)

    subset = [s for s in scenarios if s.id in set(sensitivity_ids)]
    sens = run_sensitivity(subset, weight_settings, max_iterations, cache_dir)

    losses = pd.concat([
        ties_and_losses(main["results"], "main", descriptions=descriptions),
        ties_and_losses(scale, "scalability", descriptions={s.id: s.description for s in scale_scenarios}),
        *[ties_and_losses(g, "sensitivity", label, descriptions)
          for label, g in sens.groupby("setting", sort=False)],
    ], ignore_index=True)

    tables = {
        **main,
        "objective_check": check,
        "objective_check_summary": objective_check_summary(check) if len(check) else pd.DataFrame(),
        "scalability": scale, "scalability_summary": scalability_summary(scale),
        "sensitivity": sens, "sensitivity_summary": sensitivity_summary(sens),
        "ties_and_losses": losses,
    }
    for key in ("objective_check", "scalability", "scalability_summary", "sensitivity",
                "sensitivity_summary", "ties_and_losses"):
        tables[key].to_csv(out_dir / f"{key}.csv", index=False)
    tables["_scenarios"] = scenarios  # for the report only, not written
    return tables


def report_v3(tables: Mapping) -> str:
    lines = ["#" * 30 + " PART 1: main evaluation with the conflict penalty " + "#" * 30,
             report(tables, tables["_scenarios"]), ""]
    if len(tables["objective_check"]):
        check = tables["objective_check"]
        naive_changed = check[(check["method"] == NAIVE) & check["changed"]]
        lines += ["=== 1c. v2 vs v3 objective (plans are identical; only the objective changed) ===",
                  tables["objective_check_summary"].to_string(index=False),
                  "naive runs whose objective changed (diff = -CONFLICT_PENALTY x conflicting stops):",
                  naive_changed[["scenario_id", "weights", "conflicts", "objective_score_v2",
                                 "objective_score_v3", "diff"]].to_string(index=False), ""]

    s = tables["scalability_summary"]
    lines += ["#" * 30 + " PART 2: scalability (real + SYNTHETIC places, default weights) " + "#" * 30,
              s.drop(columns=["budget"]).to_string(index=False),
              f"joint improves the objective in {(s['obj_gain'] >= EPS).sum()} of {len(s)} trips; "
              f"verdict 'better' in {(s['verdict'] == 'better').sum()} of {len(s)}; "
              f"slowest joint run {s['joint_runtime_s'].max():.1f} s", ""]

    ss = tables["sensitivity_summary"]
    lines += ["#" * 30 + " PART 3: sensitivity (" + ", ".join(SENSITIVITY_SCENARIOS) + " x 3 weight settings) "
              + "#" * 30,
              ss[["setting", "runs", "better", "same", "mixed", "worse", "obj_improved", "obj_ties",
                  "mean_obj_gain", "mean_diff_score_coll", "mean_diff_places", "travel_reduction_of_totals_pct",
                  "seq_adherence", "joint_adherence", "naive_obj_above_joint"]].to_string(index=False), "",
              "conclusions under each setting (True = the statement holds):",
              ss[["setting", *CONCLUSIONS, "conclusions_same"]].to_string(index=False),
              "changed vs default: " + "; ".join(f"{r['setting']}: {r['changed_conclusions']}"
                                                 for _, r in ss.iterrows() if r["setting"] != DEFAULT_SETTING),
              ""]

    losses = tables["ties_and_losses"]
    lines.append("#" * 30 + " PART 4: EVERY run where joint ties or loses (all parts) " + "#" * 30)
    for part, g in losses.groupby("part", sort=False):
        lines.append(f"--- {part}: {len(g)} runs ---")
        lines.append(g.drop(columns=["part", "description"] + (["setting"] if part != "sensitivity" else []))
                     .to_string(index=False))
    if not len(losses):
        lines.append("none")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--iterations", type=int, default=config.JOINT_MAX_ITERATIONS)
    parser.add_argument("--out-dir", type=Path, default=RESULTS_DIR)
    args = parser.parse_args(argv)

    start = time.perf_counter()
    tables = run_v3(out_dir=args.out_dir, max_iterations=args.iterations)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 40)
    pd.set_option("display.max_rows", 500)
    print(report_v3(tables))
    print(f"\nWritten to {args.out_dir} in {time.perf_counter() - start:.0f} s")


if __name__ == "__main__":
    main()
