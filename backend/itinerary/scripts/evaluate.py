"""Evaluate the joint optimizer against the baselines on every scenario (versions 2 and 3).

    python scripts/evaluate.py                # all scenarios, all weight settings
    python scripts/evaluate.py --scenarios S01 S07 --iterations 500

For every scenario (src/scenarios.py) and every weight setting
(config.EVALUATION_WEIGHT_SETTINGS) it runs four methods:

    naive       distance-only route, no opening-hours check (run_naive)
    sequential  route first, then hours, then budget (run_sequential)
    joint       restarts + simulated annealing on the joint objective (optimize_joint)
    exact       the best possible plan under the objective (exact_benchmark),
                only for scenarios with <= config.EXACT_MAX_PLACES places

and writes to data/results/v3/ by default. Earlier results are left untouched:
data/results/ (version 1) and data/results/v2/ (version 2, made BEFORE the opening-hour
conflict penalty was added to the objective, so its naive objective scores are higher).
scripts/evaluate_v3.py runs this plus the scalability and sensitivity checks.

    results.csv             one row per scenario x weight setting x method
    summary.csv             joint minus sequential per scenario, plus MEAN rows (as in v1)
    method_means.csv        mean of every metric per method and weight setting
    method_means_small.csv  the same, only the small scenarios that have an exact plan
    exact_gap.csv           objective of sequential / joint / exact on the small scenarios
    *.png                   charts for the report

The objective score is reported but NOT used as the main comparison, because the
joint optimizer maximises it directly. The main comparison uses measures it does
not see directly: travel per place, score collected, waiting, budget, conflicts.
All inputs are mock data and the travel matrix is the APPROX haversine estimate.
"""

import argparse
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # write PNG files, no window
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # allow "python scripts/evaluate.py"

from src import config  # noqa: E402
from src.exact import exact_benchmark  # noqa: E402
from src.joint import optimize_joint  # noqa: E402
from src.metrics import evaluate_plan, travel_time_reduction_pct  # noqa: E402
from src.objective import score_plan  # noqa: E402
from src.pipeline import run_naive, run_sequential  # noqa: E402
from src.scenarios import Scenario, build_scenarios  # noqa: E402

RESULTS_DIR = config.DATA_DIR / "results" / "v3"  # v1 (data/results/) and v2 files are never overwritten
NAIVE, SEQ, JOINT, EXACT = "naive", "sequential", "joint", "exact"
HOURS_WORDS = ("closing", "opens", "open only")  # unscheduled reasons that are about opening hours
EPS = 0.01  # differences smaller than this count as "equal"


# ---------- One plan -> one row ----------

def _row(scenario: Scenario, weight_name: str, method: str, result, objective: float,
         runtime_s: float) -> dict:
    """All reported numbers for one plan."""
    it = result.itinerary
    m = evaluate_plan(it.days, it.unscheduled, result.budget_report, result.graph)
    stops = [s for d in it.days for s in d.stops]
    budget = scenario.trip.total_budget_lkr
    return {
        "scenario_id": scenario.id,
        "tags": ", ".join(scenario.tags),
        "weights": weight_name,
        "method": method,
        "travel_min": m.travel_time_min,
        # Blank (NaN) for an empty plan: 0 would wrongly look like the best possible value.
        "travel_min_per_place": round(m.travel_time_min / m.num_scheduled, 2) if m.num_scheduled else float("nan"),
        "within_budget": "yes" if m.within_budget else "no",
        "overrun_lkr": m.overrun_lkr,
        "total_cost_lkr": it.total_cost_lkr,
        "budget_lkr": budget,
        "budget_used_pct": round(it.total_cost_lkr / budget * 100, 1) if budget else 0.0,
        "conflicts": len(m.conflicts),
        "conflict_rate": round(m.conflict_rate, 4),
        "places_scheduled": m.num_scheduled,
        "places_unscheduled": m.num_unscheduled,
        "unscheduled_hours": sum(any(w in u.reason for w in HOURS_WORDS) for u in it.unscheduled),
        "score_collected": round(sum(s.score for s in stops), 3),  # independent of the weights
        "wait_min": round(sum(s.wait_min for s in stops), 1),
        "objective_score": objective,
        "runtime_s": round(runtime_s, 3),
    }


def _timed(fn, *args, **kwargs):
    start = time.perf_counter()
    result = fn(*args, **kwargs)
    return result, time.perf_counter() - start


def _rescore(result, weights) -> float:
    """Objective of a plan under the given weights (naive and sequential plans ignore weights)."""
    it = result.itinerary
    return score_plan(it.days, it.unscheduled, result.budget_report, weights, result.graph).total


def evaluate_scenario(scenario: Scenario, weight_settings: Mapping[str, Mapping[str, float]],
                      max_iterations: int, cache_dir: Path, run_exact: bool = True,
                      row_fn=_row) -> list[dict]:
    """Rows for every method under every weight setting.

    With config.USE_TRANSPORT_MODES on (version 5) the transport mode of each leg depends on
    the weights, so naive and sequential are rebuilt per weight setting; otherwise once.
    row_fn builds one row (scripts/evaluate_v5.py adds columns this way).
    """
    dests, trip = scenario.destinations, scenario.trip
    per_weight = config.USE_TRANSPORT_MODES
    if not per_weight:
        naive, naive_time = _timed(run_naive, dests, trip, cache_dir=cache_dir)
        seq, seq_time = _timed(run_sequential, dests, trip, cache_dir=cache_dir)
    small = run_exact and len(dests) <= config.EXACT_MAX_PLACES

    rows = []
    for name, weights in weight_settings.items():
        if per_weight:
            naive, naive_time = _timed(run_naive, dests, trip, cache_dir=cache_dir, mode_weights=weights)
            seq, seq_time = _timed(run_sequential, dests, trip, cache_dir=cache_dir, mode_weights=weights)
        rows.append(row_fn(scenario, name, NAIVE, naive, _rescore(naive, weights), naive_time))
        rows.append(row_fn(scenario, name, SEQ, seq, _rescore(seq, weights), seq_time))
        # joint and exact times include building their own sequential plan
        jnt, t = _timed(optimize_joint, dests, trip, weights=weights, max_iterations=max_iterations,
                        seed=config.JOINT_SEED, cache_dir=cache_dir)
        rows.append(row_fn(scenario, name, JOINT, jnt, jnt.score.total, t))
        if small:
            ex, t = _timed(exact_benchmark, dests, trip, weights=weights, cache_dir=cache_dir)
            rows.append(row_fn(scenario, name, EXACT, ex, ex.score.total, t))
    return rows


# ---------- Summary: joint minus sequential ----------

# (column, True if higher is better). These decide the verdict; objective score is left out.
VERDICT_METRICS = [
    ("within_budget", True), ("overrun_lkr", False), ("conflicts", False),
    ("places_scheduled", True), ("score_collected", True),
    ("travel_min_per_place", False), ("wait_min", False),
]
TOTAL_WAIT = "total_wait_min"  # waiting incl. idle before lunch (rows from scripts/evaluate_v5.py)


def verdict_metrics() -> list[tuple[str, bool]]:
    """VERDICT_METRICS, with wait_min swapped for total_wait_min when config.VERDICT_USE_TOTAL_WAIT is on.

    Swapped, not added: total_wait_min already contains wait_min, so adding it would count it twice.
    """
    if not config.VERDICT_USE_TOTAL_WAIT:
        return VERDICT_METRICS
    return [(TOTAL_WAIT if col == "wait_min" else col, hib) for col, hib in VERDICT_METRICS]


def verdict(seq: pd.Series, jnt: pd.Series) -> str:
    """'better' / 'worse' / 'mixed' / 'same' for joint, judged on verdict_metrics() only."""
    better = worse = 0
    for col, higher_is_better in verdict_metrics():
        if col not in seq.index or col not in jnt.index:
            raise KeyError(f"verdict needs column {col!r} (VERDICT_USE_TOTAL_WAIT needs the v5 rows)")
        diff = float(jnt[col]) - float(seq[col])
        if pd.isna(diff) or abs(diff) < EPS:  # NaN: a plan with no places has no per-place value
            continue
        if (diff > 0) == higher_is_better:
            better += 1
        else:
            worse += 1
    if better and worse:
        return "mixed"
    return "better" if better else "worse" if worse else "same"


def summarise(results: pd.DataFrame) -> pd.DataFrame:
    """Per scenario x weight setting: both methods and their difference, then MEAN rows."""
    df = results.assign(within_budget=(results["within_budget"] == "yes").astype(int))
    rows = []
    for (sid, wname), group in df.groupby(["scenario_id", "weights"], sort=False):
        s = group[group["method"] == SEQ].iloc[0]
        j = group[group["method"] == JOINT].iloc[0]
        row = {"scenario_id": sid, "weights": wname,
               "travel_reduction_pct": travel_time_reduction_pct(s["travel_min"], j["travel_min"])}
        extra = (TOTAL_WAIT,) if config.VERDICT_USE_TOTAL_WAIT else ()  # flag off: columns as in v1-v5
        for col in ("travel_min_per_place", "within_budget", "overrun_lkr", "conflict_rate",
                    "places_scheduled", "score_collected", "wait_min", *extra):
            row[f"seq_{col}"], row[f"joint_{col}"] = s[col], j[col]
            row[f"diff_{col}"] = round(j[col] - s[col], 4)
        row["verdict"] = verdict(s, j)
        rows.append(row)
    per_scenario = pd.DataFrame(rows)

    # MEAN rows: for the 0/1 within_budget columns the mean IS the budget-adherence rate.
    numeric = per_scenario.drop(columns=["scenario_id", "weights", "verdict"])
    means = []
    for wname, group in [*per_scenario.groupby("weights", sort=False), ("all", per_scenario)]:
        mean = numeric.loc[group.index].mean().round(4).to_dict()
        counts = group["verdict"].value_counts()
        mean["verdict"] = ", ".join(f"{k}={counts.get(k, 0)}" for k in ("better", "same", "mixed", "worse"))
        means.append({"scenario_id": "MEAN", "weights": wname, **mean})
    return pd.concat([per_scenario, pd.DataFrame(means)], ignore_index=True)


# ---------- Per-method means and the exact gap ----------

MEAN_COLUMNS = ["travel_min", "travel_min_per_place", "within_budget", "overrun_lkr", "conflicts",
                "conflict_rate", "places_scheduled", "score_collected", "wait_min", "objective_score",
                "runtime_s"]


def method_means(results: pd.DataFrame, scenario_ids: Sequence[str] | None = None) -> pd.DataFrame:
    """Mean of each metric per weight setting x method (within_budget mean = adherence rate).

    Pass scenario_ids to restrict to a subset (e.g. the small scenarios that have an exact plan).
    """
    df = results.assign(within_budget=(results["within_budget"] == "yes").astype(int))
    if scenario_ids is not None:
        df = df[df["scenario_id"].isin(scenario_ids)]
    # travel reduction vs sequential, per scenario (sequential itself is 0 by definition)
    seq_travel = df[df["method"] == SEQ].set_index(["scenario_id", "weights"])["travel_min"]
    df = df.assign(travel_reduction_vs_seq_pct=[
        travel_time_reduction_pct(seq_travel[(sid, w)], t)
        for sid, w, t in zip(df["scenario_id"], df["weights"], df["travel_min"])])
    groups = df.groupby(["weights", "method"], sort=False)
    out = groups[["travel_reduction_vs_seq_pct", *MEAN_COLUMNS]].mean().round(3)
    out.insert(0, "scenarios", groups["scenario_id"].nunique())
    # A mean of percentages explodes when sequential drives almost nothing (S12: 2 min), so also
    # report the reduction of the summed travel over the same scenarios.
    out.insert(2, "travel_reduction_of_totals_pct", [
        travel_time_reduction_pct(seq_travel[[(sid, w) for sid in g["scenario_id"]]].sum(), g["travel_min"].sum())
        for (w, _), g in groups])
    return out.reset_index()


def exact_gaps(results: pd.DataFrame) -> pd.DataFrame:
    """Objective of naive, sequential, joint and exact side by side, where an exact plan exists.

    gap = exact - method (0 means the method found the optimum). share_closed = how much of
    the sequential-to-exact gap the joint optimizer closed (blank when there was no gap).
    """
    rows = []
    for (sid, wname), g in results.groupby(["scenario_id", "weights"], sort=False):
        if EXACT not in set(g["method"]):
            continue
        obj = g.set_index("method")["objective_score"]
        seq_gap, joint_gap = obj[EXACT] - obj[SEQ], obj[EXACT] - obj[JOINT]
        rows.append({
            "scenario_id": sid, "weights": wname,
            "naive_obj": obj[NAIVE], "seq_obj": obj[SEQ], "joint_obj": obj[JOINT], "exact_obj": obj[EXACT],
            "seq_gap": round(seq_gap, 4), "joint_gap": round(joint_gap, 4),
            "joint_optimal": "yes" if joint_gap < EPS else "no",
            "share_closed_pct": round((obj[JOINT] - obj[SEQ]) / seq_gap * 100, 1) if seq_gap >= EPS else float("nan"),
            "exact_runtime_s": g.set_index("method")["runtime_s"][EXACT],
        })
    return pd.DataFrame(rows)


# ---------- Charts ----------

# Reference categorical palette (dataviz skill, light mode, checked with validate_palette.js).
# Sequential baseline in neutral grey; naive takes the next fixed slot (4, yellow).
COLORS = {SEQ: "#8a8985", NAIVE: "#eda100", "default": "#2a78d6", "budget": "#eb6834", "time": "#1baf7a"}


def _series(results: pd.DataFrame) -> list[tuple[str, pd.DataFrame]]:
    """(label, rows) per bar series: naive and sequential once (weights don't change their plans),
    then joint per weight setting."""
    once = results[results["weights"] == results["weights"].iloc[0]]
    out = [("Naive (no hours check)", once[once["method"] == NAIVE]),
           ("Sequential baseline", once[once["method"] == SEQ])]
    for wname in results["weights"].unique():
        out.append((f"Joint ({wname} weights)", results[(results["method"] == JOINT) & (results["weights"] == wname)]))
    return out


def _color(label: str) -> str:
    if label.startswith("Naive"):
        return COLORS[NAIVE]
    return COLORS[SEQ] if label.startswith("Sequential") else COLORS.get(label.split("(")[1].split()[0], "#6250d6")


def _style():
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False,
                         "axes.grid": True, "axes.grid.axis": "y", "grid.color": "#e4e3df",
                         "axes.axisbelow": True, "axes.edgecolor": "#8a8985", "figure.dpi": 150})


def _grouped_bars(ax, results: pd.DataFrame, column: str):
    series = _series(results)
    ids = list(results["scenario_id"].unique())
    width = 0.8 / len(series)
    for k, (label, rows) in enumerate(series):
        rows = rows.set_index("scenario_id").loc[ids]
        xs = [i + (k - (len(series) - 1) / 2) * width for i in range(len(ids))]
        ax.bar(xs, rows[column].fillna(0), width * 0.9, label=label, color=_color(label))
        for x, n in zip(xs, rows["places_scheduled"]):
            if n == 0:  # an empty plan has no bar; say so instead of leaving a silent gap
                ax.text(x, 0, "0 places", rotation=90, ha="center", va="bottom", fontsize=7, color="#52514e")
    ax.set_xticks(range(len(ids)), ids)
    ax.set_xlim(-0.6, len(ids) - 0.4)


def _legend_below(fig, ax):
    fig.legend(*ax.get_legend_handles_labels(), ncols=5, loc="lower center", frameon=False)
    fig.tight_layout(rect=(0, 0.06, 1, 1))


def chart_travel(results: pd.DataFrame, path: Path):
    fig, (top, bottom) = plt.subplots(2, 1, figsize=(12, 7), sharex=True)
    _grouped_bars(top, results, "travel_min")
    top.set_ylabel("Total travel time (min)")
    top.set_title("Travel time per scenario: naive and sequential baselines vs joint optimizer")
    _grouped_bars(bottom, results, "travel_min_per_place")
    bottom.set_ylabel("Travel min per scheduled place")
    bottom.set_xlabel("Scenario")
    _legend_below(fig, top)
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


def chart_budget(results: pd.DataFrame, path: Path):
    fig, ax = plt.subplots(figsize=(12, 4.5))
    _grouped_bars(ax, results, "budget_used_pct")
    ax.axhline(100, color="#0b0b0b", linestyle="--", linewidth=1)
    ax.text(len(results["scenario_id"].unique()) - 0.45, 100, " budget limit", va="bottom", ha="right",
            fontsize=9, color="#52514e")
    ax.set_ylabel("Planned cost (% of total budget)")
    ax.set_xlabel("Scenario")
    ax.set_title("Budget adherence per scenario (bars above the dashed line are over budget)")
    _legend_below(fig, ax)
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


def chart_summary(means: pd.DataFrame, n_scenarios: int, path: Path):
    """Mean of the headline metrics per method, from method_means() over all scenarios."""
    weight_names = list(means["weights"].unique())
    first = means[means["weights"] == weight_names[0]].set_index("method")
    joint = means[means["method"] == JOINT].set_index("weights")
    labels = ["Naive", "Sequential"] + [f"Joint\n({w})" for w in weight_names]
    colors = [COLORS[NAIVE], COLORS[SEQ]] + [COLORS.get(w, "#6250d6") for w in weight_names]

    def values(col, scale=1.0):
        baselines = [first.loc[NAIVE, col], first.loc[SEQ, col]]
        return [v * scale for v in baselines + [joint.loc[w, col] for w in weight_names]]

    panels = [
        ("Total travel-time reduction vs sequential (%)", values("travel_reduction_of_totals_pct")),
        ("Budget-adherence rate (%)", values("within_budget", 100)),
        ("Opening-hour conflict rate (%)", values("conflict_rate", 100)),
        ("Places scheduled (mean per trip)", values("places_scheduled")),
    ]
    fig, axes = plt.subplots(2, 2, figsize=(12, 7.5))
    for ax, (title, vals) in zip(axes.flat, panels):
        bars = ax.bar(range(len(labels)), vals, 0.6, color=colors)
        ax.bar_label(bars, fmt="%.1f", padding=2, fontsize=9)
        ax.axhline(0, color="#8a8985", linewidth=0.8)
        ax.set_xticks(range(len(labels)), labels)
        ax.set_title(title, fontsize=10)
        low, high = min(0, min(vals)), max(vals)
        ax.set_ylim(low * 1.25, high * 1.2 if high > 0 else 1)  # all-zero panels still get a sane axis
        if not any(vals):
            ax.text(0.5, 0.5, "0 in every plan", transform=ax.transAxes, ha="center", color="#52514e")
    axes.flat[0].set_xticks(range(len(labels)), ["Naive", "Sequential\n(reference)", *labels[2:]])
    fig.suptitle(f"Mean over {n_scenarios} scenarios: baselines vs joint optimizer")
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


def chart_exact_gap(gaps: pd.DataFrame, path: Path):
    """Objective gap to the exact optimum (0 = optimal) for sequential and joint, small scenarios only."""
    weight_names = list(gaps["weights"].unique())
    fig, axes = plt.subplots(1, len(weight_names), figsize=(4.2 * len(weight_names), 4),
                             sharey=True, squeeze=False)
    for ax, wname in zip(axes[0], weight_names):
        g = gaps[gaps["weights"] == wname]
        xs = list(range(len(g)))
        ax.bar([x - 0.2 for x in xs], g["seq_gap"], 0.36, color=COLORS[SEQ], label="Sequential")
        ax.bar([x + 0.2 for x in xs], g["joint_gap"], 0.36, color=COLORS.get(wname, "#6250d6"), label="Joint")
        for x, gap in zip(xs, g["joint_gap"]):
            if gap < EPS:  # a zero-height bar is invisible; say the joint plan is optimal instead
                ax.text(x + 0.2, 0, "opt", rotation=90, ha="center", va="bottom", fontsize=7, color="#52514e")
        ax.set_xticks(xs, g["scenario_id"])
        ax.set_title(f"{wname} weights", fontsize=10)
        ax.legend(frameon=False, fontsize=8)
    axes[0][0].set_ylabel("Exact objective minus method objective")
    fig.suptitle("Gap to the exact optimum under the same objective (lower is better; 'opt' = joint is optimal)")
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


# ---------- Run everything ----------

TABLE_FILES = {"results": "results.csv", "summary": "summary.csv", "means": "method_means.csv",
               "means_small": "method_means_small.csv", "exact_gap": "exact_gap.csv"}


def run_evaluation(scenarios: Sequence[Scenario],
                   weight_settings: Mapping[str, Mapping[str, float]] = config.EVALUATION_WEIGHT_SETTINGS,
                   out_dir: Path = RESULTS_DIR, cache_dir: Path = config.CACHE_DIR,
                   max_iterations: int = config.JOINT_MAX_ITERATIONS,
                   run_exact: bool = True, row_fn=_row) -> dict[str, pd.DataFrame]:
    """Run all scenarios, write the CSVs and charts to out_dir.

    Returns the tables {"results", "summary", "means", "means_small", "exact_gap"}.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = [row for sc in scenarios
            for row in evaluate_scenario(sc, weight_settings, max_iterations, cache_dir, run_exact, row_fn)]
    results = pd.DataFrame(rows)
    gaps = exact_gaps(results)
    small_ids = list(gaps["scenario_id"].unique()) if len(gaps) else []
    tables = {
        "results": results,
        "summary": summarise(results),
        "means": method_means(results),
        # same means on the small scenarios only, so all four methods are compared on equal ground
        "means_small": method_means(results, small_ids) if small_ids else pd.DataFrame(),
        "exact_gap": gaps,
    }
    for key, name in TABLE_FILES.items():
        tables[key].to_csv(out_dir / name, index=False)

    _style()
    chart_travel(results, out_dir / "travel_time.png")
    chart_budget(results, out_dir / "budget_adherence.png")
    chart_summary(tables["means"], results["scenario_id"].nunique(), out_dir / "summary_metrics.png")
    if len(gaps):
        chart_exact_gap(gaps, out_dir / "exact_gap.png")
    return tables


def report(tables: Mapping[str, pd.DataFrame], scenarios: Sequence[Scenario]) -> str:
    """Plain-text summary for the console, including every run where joint ties or loses."""
    summary, means, gaps, results = tables["summary"], tables["means"], tables["exact_gap"], tables["results"]
    desc = {s.id: s.description for s in scenarios}
    per = summary[summary["scenario_id"] != "MEAN"]
    lines = ["=== 1. Mean per method, all scenarios (within_budget = budget-adherence rate) ===",
             means[["weights", "method", "scenarios", "travel_reduction_vs_seq_pct", "travel_reduction_of_totals_pct",
                    "travel_min_per_place",
                    "within_budget", "conflicts", "conflict_rate", "places_scheduled", "score_collected",
                    "wait_min", "objective_score", "runtime_s"]].to_string(index=False), ""]
    if len(tables["means_small"]):
        lines += [f"=== 1b. Same, only the {gaps['scenario_id'].nunique()} small scenarios with an exact plan ===",
                  tables["means_small"][["weights", "method", "travel_reduction_vs_seq_pct", "travel_reduction_of_totals_pct",
                                         "within_budget",
                                         "conflicts", "places_scheduled", "score_collected",
                                         "objective_score", "runtime_s"]].to_string(index=False), ""]

    naive = results[(results["method"] == NAIVE) & (results["weights"] == results["weights"].iloc[0])]
    same_plan = ("same plan under every weight setting" if not config.USE_TRANSPORT_MODES
                 else f"{results['weights'].iloc[0]} weights; with transport modes the plan depends on the weights")
    lines += [f"=== 2. Naive baseline: opening-hour conflicts it causes ({same_plan}) ===",
              naive[["scenario_id", "places_scheduled", "conflicts", "conflict_rate", "travel_min",
                     "within_budget"]].to_string(index=False),
              f"total: {int(naive['conflicts'].sum())} conflicts in {int(naive['places_scheduled'].sum())} "
              f"scheduled visits; {int((naive['conflicts'] > 0).sum())} of {len(naive)} scenarios have at least one",
              ""]

    lines += ["=== 3. Joint vs sequential per scenario (as in v1) ===",
              per[["scenario_id", "weights", "travel_reduction_pct", "seq_within_budget", "joint_within_budget",
                   "seq_places_scheduled", "joint_places_scheduled", "diff_score_collected",
                   "diff_travel_min_per_place", "diff_wait_min", "verdict"]].to_string(index=False), "",
              summary[summary["scenario_id"] == "MEAN"][["weights", "travel_reduction_pct", "seq_within_budget",
                                                         "joint_within_budget", "verdict"]].to_string(index=False),
              ""]

    if len(gaps):
        lines += ["=== 4. Gap to the exact optimum (same objective; gap 0 = optimal) ===",
                  gaps.drop(columns=["exact_runtime_s"]).to_string(index=False),
                  f"joint optimal in {(gaps['joint_optimal'] == 'yes').sum()} of {len(gaps)}; "
                  f"sequential optimal in {(gaps['seq_gap'] < EPS).sum()} of {len(gaps)}; "
                  f"mean gap sequential {gaps['seq_gap'].mean():.3f}, joint {gaps['joint_gap'].mean():.3f}; "
                  f"slowest exact run {gaps['exact_runtime_s'].max():.2f} s", ""]

    # Honesty rule: list every run where joint is not clearly better, from every angle.
    lines.append("=== 5. Every run where joint ties or loses ===")
    not_better = per[per["verdict"] != "better"]
    lines.append(f"(a) Verdict on independent metrics is NOT 'better' in {len(not_better)} of {len(per)} runs:")
    lines += [f"  {r['scenario_id']} [{r['weights']}] {r['verdict']}: {desc.get(r['scenario_id'], '')}"
              for _, r in not_better.iterrows()]
    obj = results.pivot_table(index=["scenario_id", "weights"], columns="method", values="objective_score")
    ties = obj[(obj[JOINT] - obj[SEQ]).abs() < EPS]
    lines.append(f"(b) Joint objective equals sequential (no improvement found) in {len(ties)} of {len(obj)} runs:")
    lines += [f"  {sid} [{w}]" for sid, w in ties.index]
    if len(gaps):
        short = gaps[gaps["joint_optimal"] == "no"]
        lines.append(f"(c) Joint below the exact optimum in {len(short)} of {len(gaps)} small runs:")
        lines += [f"  {r['scenario_id']} [{r['weights']}] gap {r['joint_gap']:.3f}" for _, r in short.iterrows()]
    beaten = obj[obj[NAIVE] > obj[JOINT] + EPS]
    lines.append(f"(d) Naive objective above joint in {len(beaten)} of {len(obj)} runs "
                 "(naive ignores opening hours, so such a plan may be impossible to follow):")
    lines += [f"  {sid} [{w}]" for sid, w in beaten.index]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scenarios", nargs="*", help="scenario ids to run (default: all)")
    parser.add_argument("--iterations", type=int, default=config.JOINT_MAX_ITERATIONS)
    parser.add_argument("--out-dir", type=Path, default=RESULTS_DIR)
    parser.add_argument("--no-exact", action="store_true", help="skip the exact benchmark")
    args = parser.parse_args(argv)

    scenarios = build_scenarios()
    if args.scenarios:
        scenarios = [s for s in scenarios if s.id in set(args.scenarios)]
    start = time.perf_counter()
    tables = run_evaluation(scenarios, out_dir=args.out_dir, max_iterations=args.iterations,
                            run_exact=not args.no_exact)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 30)
    print(report(tables, scenarios))
    print(f"\nWritten to {args.out_dir} in {time.perf_counter() - start:.0f} s: "
          f"{', '.join(TABLE_FILES.values())} and charts")


if __name__ == "__main__":
    main()
