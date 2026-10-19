"""Version 5 evaluation: the traveller rules (transport modes, hill speeds, lunch break,
per-day start times, evening drives, daily living costs).

    python scripts/evaluate_v5.py                          # everything (about 10 minutes)
    python scripts/evaluate_v5.py --parts repro main       # only parts 0 and 1

Everything goes to data/results/v5/. v1 (data/results/), v2, v3 and v4 are only READ.
Fixed before any v5 run; no scenario or weight was changed after seeing results.

    0. Reproduction: every v5 flag OFF, the main evaluation rerun. Every v3 column except
       runtime_s is compared with data/results/v3/results.csv; all must be identical.
       reproduction.csv          one row per run: matches or not, and which columns differ
    1. Main evaluation with ALL v5 config rules ON (transport modes, hill speeds, lunch
       break, evening drives up to EVENING_DRIVE_LIMIT_MIN, daily living costs).
       Per-day start times are a traveller input, not a config rule: see part 2.
       Same 15 scenarios x 3 weight settings x 4 methods as v3: results.csv, summary.csv,
       method_means*.csv, exact_gap.csv and the charts. Naive and sequential are rebuilt per
       weight setting (the transport mode of each leg depends on the weights).
       rule_usage.csv            how often each rule acted, per method and weight setting
       budget_breakdown.csv      mean planned cost per category, per method and weight setting
    2. Ablation: each rule ON alone, plus "early start" (days 2+ start at 06:00, day 1 as
       in the scenario). Same scenarios, weights and methods.
       ablation.csv              one row per setting x scenario x weights x method
       ablation_means.csv        mean per setting x method, and the change vs all rules off
       ablation_summary.csv      joint vs sequential per setting (as v3's sensitivity summary)
    3. Scalability with all rules on (15 / 20 / 30 / 50 places, real + SYNTHETIC):
       scalability.csv, scalability_summary.csv
    4. ties_and_losses.csv       EVERY run, in parts 1-3, where joint ties or loses.

All inputs are mock (or SYNTHETIC) data, travel times are APPROX haversine estimates, and
every v5 value (speeds, fares, lunch, accommodation, food) is an APPROX value in config.py.
"""

import argparse
import sys
import time
from collections.abc import Mapping, Sequence
from datetime import time as clock_time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # allow "python scripts/evaluate_v5.py"

from scripts.evaluate import EPS, _row, report, run_evaluation  # noqa: E402
from scripts.evaluate_v3 import (_one_setting_summary, overridden, run_scalability,  # noqa: E402
                                 scalability_summary, ties_and_losses)
from src import config  # noqa: E402
from src.budget import COST_CATEGORIES, cost_breakdown  # noqa: E402
from src.scenarios import Scenario, build_scalability_scenarios, build_scenarios  # noqa: E402

RESULTS_DIR = config.DATA_DIR / "results" / "v5"
V3_RESULTS = config.DATA_DIR / "results" / "v3" / "results.csv"
PROTECTED = [config.DATA_DIR / "results", *(config.DATA_DIR / "results" / v for v in ("v2", "v3", "v4"))]

V5_FLAGS = ("USE_TRANSPORT_MODES", "USE_REGION_SPEEDS", "USE_LUNCH_BREAK", "USE_EVENING_DRIVE",
            "USE_DAILY_COSTS")
ALL_OFF = {flag: False for flag in V5_FLAGS}
ALL_ON = {flag: True for flag in V5_FLAGS}
EARLY_START = clock_time(6, 0)  # APPROX: a typical early hike / safari start
OFF_LABEL, ALL_LABEL = "all rules off (v3)", "all rules on"


def early_start(sc: Scenario) -> Scenario:
    """Days 2+ start at EARLY_START; day 1 keeps the scenario's start (the traveller arrives)."""
    starts = [sc.trip.day_start] + [EARLY_START] * (sc.trip.num_days - 1)
    return sc._replace(trip=sc.trip.model_copy(update={"day_starts": starts}))


# (label, config overrides, scenario change). Each rule is switched on alone.
ABLATION = [
    ("transport modes", {"USE_TRANSPORT_MODES": True}, None),
    ("hill speeds", {"USE_REGION_SPEEDS": True}, None),
    ("lunch break", {"USE_LUNCH_BREAK": True}, None),
    ("evening drive", {"USE_EVENING_DRIVE": True}, None),
    ("daily costs", {"USE_DAILY_COSTS": True}, None),
    ("early start days 2+", {}, early_start),
]


# ---------- Rows with the v5 columns ----------

def _row_v5(scenario, weight_name, method, result, objective, runtime_s) -> dict:
    """The v3 row plus what the v5 rules did in this plan and its cost per category."""
    row = _row(scenario, weight_name, method, result, objective, runtime_s)
    days = result.itinerary.days
    stops = [s for d in days for s in d.stops]
    modes = [m for s in stops for m in (s.travel_mode or "").split("+") if m]
    lunch_wait = sum(d.lunch.wait_min for d in days if d.lunch)
    row.update({
        "lunch_stops": sum(d.lunch is not None for d in days),
        "lunch_wait_min": round(lunch_wait, 1),
        "total_wait_min": round(row["wait_min"] + lunch_wait, 1),  # what the objective counts
        "evening_drives": sum(s.evening_drive for s in stops),
        **{f"legs_{m}": modes.count(m) for m in config.TRANSPORT_MODES},
        **{f"cost_{c}": v for c, v in cost_breakdown(days).items()},
    })
    return row


# ---------- 0. Reproduction ----------

def reproduction(rerun: pd.DataFrame, v3_path: Path = V3_RESULTS) -> pd.DataFrame:
    """Every run of the flags-off rerun next to v3, compared on every v3 column except runtime."""
    if not Path(v3_path).exists():
        return pd.DataFrame()
    v3 = pd.read_csv(v3_path)
    keys = ["scenario_id", "weights", "method"]
    columns = [c for c in v3.columns if c not in (*keys, "runtime_s")]
    new = rerun[[*keys, *columns]].set_index(keys)
    old = v3[[*keys, *columns]].set_index(keys)
    rows = []
    for key in old.index.union(new.index):
        if key not in new.index or key not in old.index:
            rows.append({**dict(zip(keys, key)), "matches": False, "differing_columns": "missing run"})
            continue
        diff = [c for c in columns if not _same(old.loc[key, c], new.loc[key, c])]
        rows.append({**dict(zip(keys, key)), "matches": not diff, "differing_columns": ", ".join(diff)})
    return pd.DataFrame(rows)


def _same(a, b) -> bool:
    if pd.isna(a) and pd.isna(b):
        return True
    if pd.api.types.is_number(a) and pd.api.types.is_number(b):
        return abs(float(a) - float(b)) < 1e-9
    return str(a) == str(b)


# ---------- 1. Rule usage and budget breakdown ----------

USAGE_COLUMNS = ["legs_car", "legs_bus", "legs_walk", "lunch_stops", "lunch_wait_min", "evening_drives",
                 "places_scheduled"]


def rule_usage(results: pd.DataFrame) -> pd.DataFrame:
    """Totals over all scenarios: how often each rule acted, per weight setting and method."""
    out = results.groupby(["weights", "method"], sort=False)[USAGE_COLUMNS].sum().reset_index()
    legs = out[["legs_car", "legs_bus", "legs_walk"]].sum(axis=1)
    out["bus_share_pct"] = (100 * out["legs_bus"] / legs.where(legs > 0)).round(1)
    return out


def budget_breakdown(results: pd.DataFrame) -> pd.DataFrame:
    """Mean planned cost per category (LKR per trip), per weight setting and method."""
    cols = [f"cost_{c}" for c in COST_CATEGORIES]
    out = results.groupby(["weights", "method"], sort=False)[[*cols, "total_cost_lkr", "budget_lkr"]].mean()
    out = out.round(0).reset_index()
    for c in COST_CATEGORIES:
        out[f"{c}_pct"] = (100 * out[f"cost_{c}"] / out["total_cost_lkr"]).round(1)
    out["within_budget_rate"] = results.assign(w=results["within_budget"] == "yes").groupby(
        ["weights", "method"], sort=False)["w"].mean().round(3).values
    return out


# ---------- 2. Ablation ----------

MEAN_COLS = ["places_scheduled", "score_collected", "travel_min", "travel_min_per_place", "total_wait_min",
             "total_cost_lkr", "conflicts", "objective_score"]


def run_ablation(scenarios: Sequence[Scenario], weight_settings, max_iterations: int, cache_dir: Path,
                 out_dir: Path, settings=ABLATION) -> pd.DataFrame:
    """Each setting's full tables and charts go to out_dir/ablation/<setting>/."""
    rows = []
    for label, overrides, change in settings:
        print(f"  ablation: {label}", flush=True)
        chosen = [change(sc) for sc in scenarios] if change else list(scenarios)
        with overridden(**{**ALL_OFF, **overrides}):
            table = run_evaluation(chosen, weight_settings, out_dir=out_dir / "ablation" / label.replace(" ", "_"),
                                   cache_dir=cache_dir, max_iterations=max_iterations, row_fn=_row_v5)["results"]
        rows.append(table.assign(setting=label))
    return pd.concat(rows, ignore_index=True)


def ablation_means(all_runs: pd.DataFrame) -> pd.DataFrame:
    """Mean per setting x method (all weight settings and scenarios), and the change vs all off."""
    df = all_runs.assign(within_budget=(all_runs["within_budget"] == "yes").astype(int))
    out = df.groupby(["setting", "method"], sort=False)[[*MEAN_COLS, "within_budget"]].mean().round(3).reset_index()
    base = out[out["setting"] == OFF_LABEL].set_index("method")
    for col in ("places_scheduled", "travel_min", "total_cost_lkr", "within_budget"):
        out[f"change_{col}"] = [round(v - base.loc[m, col], 3) for v, m in zip(out[col], out["method"])]
    return out


def ablation_summary(all_runs: pd.DataFrame) -> pd.DataFrame:
    """Joint vs sequential per setting: verdicts, objective ties, adherence (as v3 sensitivity)."""
    return pd.DataFrame([{"setting": label, **_one_setting_summary(g)}
                         for label, g in all_runs.groupby("setting", sort=False)])


# ---------- Run everything ----------

def _check_out_dir(out_dir: Path):
    if Path(out_dir).resolve() in {p.resolve() for p in PROTECTED}:
        raise ValueError(f"refusing to write into the v1-v4 folder {out_dir}")


def run_v5(out_dir: Path = RESULTS_DIR, cache_dir: Path = config.CACHE_DIR,
           max_iterations: int = config.JOINT_MAX_ITERATIONS,
           parts: Sequence[str] = ("repro", "main", "ablation", "scale"),
           scenario_ids: Sequence[str] | None = None,
           scale_scenarios: Sequence[Scenario] | None = None,
           weight_settings: Mapping[str, Mapping[str, float]] = config.EVALUATION_WEIGHT_SETTINGS,
           ablation=ABLATION, v3_path: Path = V3_RESULTS) -> dict:
    out_dir, cache_dir = Path(out_dir), Path(cache_dir)
    _check_out_dir(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    scenarios = build_scenarios()
    if scenario_ids:
        scenarios = [s for s in scenarios if s.id in set(scenario_ids)]
    descriptions = {s.id: s.description for s in scenarios}
    tables: dict = {"_scenarios": scenarios}
    off = main = abl = None
    losses = []

    if "repro" in parts:
        print("Part 0: reproduction with every v5 flag off", flush=True)
        with overridden(**ALL_OFF):
            off = run_evaluation(scenarios, weight_settings, out_dir=out_dir / "_flags_off", cache_dir=cache_dir,
                                 max_iterations=max_iterations, row_fn=_row_v5)["results"]
        tables["reproduction"] = reproduction(off, v3_path)

    if "main" in parts:
        print("Part 1: main evaluation with all v5 rules on", flush=True)
        with overridden(**ALL_ON):
            main = run_evaluation(scenarios, weight_settings, out_dir=out_dir, cache_dir=cache_dir,
                                  max_iterations=max_iterations, row_fn=_row_v5)
            tables["main_report"] = report(main, scenarios)  # inside: the naive heading reads the flags
        tables.update(main)
        tables["rule_usage"] = rule_usage(main["results"])
        tables["budget_breakdown"] = budget_breakdown(main["results"])
        losses.append(ties_and_losses(main["results"], "main (all rules on)", descriptions=descriptions))

    if "ablation" in parts:
        print("Part 2: ablation (each rule alone)", flush=True)
        abl = run_ablation(scenarios, weight_settings, max_iterations, cache_dir, out_dir, ablation)
        losses += [ties_and_losses(g, "ablation", label, descriptions) for label, g in abl.groupby("setting", sort=False)]
    # ablation tables: all off (part 0), each rule alone (part 2), all on (part 1), in that order
    ablation_runs = [t for t in (off.assign(setting=OFF_LABEL) if off is not None else None, abl,
                                 main["results"].assign(setting=ALL_LABEL) if main is not None else None)
                     if t is not None]
    if ablation_runs:
        all_runs = pd.concat(ablation_runs, ignore_index=True)
        tables["ablation"] = all_runs
        if OFF_LABEL in set(all_runs["setting"]):
            tables["ablation_means"] = ablation_means(all_runs)
        tables["ablation_summary"] = ablation_summary(all_runs)

    if "scale" in parts:
        print("Part 3: scalability with all v5 rules on", flush=True)
        scale_scenarios = build_scalability_scenarios() if scale_scenarios is None else scale_scenarios
        with overridden(**ALL_ON):
            scale = run_scalability(scale_scenarios, max_iterations, cache_dir)
        tables.update(scalability=scale, scalability_summary=scalability_summary(scale))
        losses.append(ties_and_losses(scale, "scalability (all rules on)",
                                      descriptions={s.id: s.description for s in scale_scenarios}))

    tables["ties_and_losses"] = pd.concat(losses, ignore_index=True) if losses else pd.DataFrame()
    for key in ("reproduction", "rule_usage", "budget_breakdown", "ablation", "ablation_means",
                "ablation_summary", "scalability", "scalability_summary", "ties_and_losses"):
        if key in tables:
            tables[key].to_csv(out_dir / f"{key}.csv", index=False)
    return tables


# ---------- Report ----------

def report_v5(tables: Mapping) -> str:
    lines = []
    if "reproduction" in tables:
        r = tables["reproduction"]
        lines += ["#" * 20 + " PART 0: reproduction (every v5 flag off vs v3 results.csv) " + "#" * 20]
        if len(r):
            bad = r[~r["matches"]]
            lines += [f"{int(r['matches'].sum())} of {len(r)} runs identical to v3 on every column except runtime_s",
                      bad.to_string(index=False) if len(bad) else "no differences", ""]
        else:
            lines += ["v3 results.csv not found: not compared", ""]
    if "main_report" in tables:
        lines += ["#" * 20 + " PART 1: main evaluation, all v5 rules on " + "#" * 20, tables["main_report"], "",
                  "=== 1d. How often each rule acted (totals over all scenarios) ===",
                  tables["rule_usage"].to_string(index=False), "",
                  "=== 1e. Budget breakdown: mean planned cost per trip by category (LKR) ===",
                  tables["budget_breakdown"].to_string(index=False), ""]
    if "ablation_means" in tables:
        m = tables["ablation_means"]
        lines += ["#" * 20 + " PART 2: ablation (each rule alone; means over scenarios x weights) " + "#" * 20,
                  m.to_string(index=False), ""]
    if "ablation_summary" in tables:
        s = tables["ablation_summary"]
        lines += ["=== 2b. Joint vs sequential per setting ===", s.to_string(index=False), ""]
    if "scalability_summary" in tables:
        s = tables["scalability_summary"]
        lines += ["#" * 20 + " PART 3: scalability, all rules on (real + SYNTHETIC places) " + "#" * 20,
                  s.drop(columns=["budget"]).to_string(index=False),
                  f"joint improves the objective in {(s['obj_gain'] >= EPS).sum()} of {len(s)} trips", ""]
    losses = tables.get("ties_and_losses", pd.DataFrame())
    lines.append("#" * 20 + " PART 4: EVERY run where joint ties or loses " + "#" * 20)
    if not len(losses):
        lines.append("none")
    for part, g in losses.groupby("part", sort=False) if len(losses) else []:
        lines.append(f"--- {part}: {len(g)} runs ---")
        lines.append(g.drop(columns=["part", "description"] + (["setting"] if part != "ablation" else []))
                     .to_string(index=False))
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--parts", nargs="+", default=["repro", "main", "ablation", "scale"],
                        choices=["repro", "main", "ablation", "scale"])
    parser.add_argument("--iterations", type=int, default=config.JOINT_MAX_ITERATIONS)
    parser.add_argument("--out-dir", type=Path, default=RESULTS_DIR)
    args = parser.parse_args(argv)

    start = time.perf_counter()
    tables = run_v5(out_dir=args.out_dir, max_iterations=args.iterations, parts=args.parts)
    pd.set_option("display.width", 260)
    pd.set_option("display.max_columns", 60)
    pd.set_option("display.max_rows", 1000)
    print(report_v5(tables))
    print(f"\nWritten to {args.out_dir} in {time.perf_counter() - start:.0f} s")


if __name__ == "__main__":
    main()
