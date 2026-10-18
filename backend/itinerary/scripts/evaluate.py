"""Evaluate the joint optimizer against the sequential baseline on every scenario.

    python scripts/evaluate.py                # all scenarios, all weight settings
    python scripts/evaluate.py --scenarios S01 S07 --iterations 500

For every scenario (src/scenarios.py) and every weight setting
(config.EVALUATION_WEIGHT_SETTINGS) it runs run_sequential and optimize_joint and writes:

    data/results/results.csv   one row per scenario x weight setting x method
    data/results/summary.csv   joint minus sequential per scenario, plus MEAN rows
    data/results/*.png         charts for the report

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
from src.joint import optimize_joint  # noqa: E402
from src.metrics import evaluate_plan, travel_time_reduction_pct  # noqa: E402
from src.objective import score_plan  # noqa: E402
from src.pipeline import run_sequential  # noqa: E402
from src.scenarios import Scenario, build_scenarios  # noqa: E402

RESULTS_DIR = config.DATA_DIR / "results"
SEQ, JOINT = "sequential", "joint"
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


def evaluate_scenario(scenario: Scenario, weight_settings: Mapping[str, Mapping[str, float]],
                      max_iterations: int, cache_dir: Path) -> list[dict]:
    """Rows for both methods under every weight setting."""
    start = time.perf_counter()
    seq = run_sequential(scenario.destinations, scenario.trip, cache_dir=cache_dir)
    seq_time = time.perf_counter() - start

    rows = []
    for name, weights in weight_settings.items():
        # The sequential plan ignores weights; only its objective score depends on them.
        seq_obj = score_plan(seq.itinerary.days, seq.itinerary.unscheduled, seq.budget_report, weights).total
        rows.append(_row(scenario, name, SEQ, seq, seq_obj, seq_time))

        start = time.perf_counter()  # joint time includes its own sequential start plan
        jnt = optimize_joint(scenario.destinations, scenario.trip, weights=weights,
                             max_iterations=max_iterations, seed=config.JOINT_SEED, cache_dir=cache_dir)
        rows.append(_row(scenario, name, JOINT, jnt, jnt.score.total, time.perf_counter() - start))
    return rows


# ---------- Summary: joint minus sequential ----------

# (column, True if higher is better). These decide the verdict; objective score is left out.
VERDICT_METRICS = [
    ("within_budget", True), ("overrun_lkr", False), ("conflicts", False),
    ("places_scheduled", True), ("score_collected", True),
    ("travel_min_per_place", False), ("wait_min", False),
]


def verdict(seq: pd.Series, jnt: pd.Series) -> str:
    """'better' / 'worse' / 'mixed' / 'same' for joint, judged on VERDICT_METRICS only."""
    better = worse = 0
    for col, higher_is_better in VERDICT_METRICS:
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
        for col in ("travel_min_per_place", "within_budget", "overrun_lkr", "conflict_rate",
                    "places_scheduled", "score_collected", "wait_min"):
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


# ---------- Charts ----------

# Reference categorical palette (dataviz skill, light mode). Baseline in neutral grey.
COLORS = {SEQ: "#8a8985", "default": "#2a78d6", "budget": "#eb6834", "time": "#1baf7a"}


def _series(results: pd.DataFrame) -> list[tuple[str, pd.DataFrame]]:
    """(label, rows) per bar series: sequential once (weights don't change its plan), then joint per weights."""
    first = results["weights"].iloc[0]
    out = [("Sequential baseline", results[(results["method"] == SEQ) & (results["weights"] == first)])]
    for wname in results["weights"].unique():
        out.append((f"Joint ({wname} weights)", results[(results["method"] == JOINT) & (results["weights"] == wname)]))
    return out


def _color(label: str) -> str:
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
    fig.legend(*ax.get_legend_handles_labels(), ncols=4, loc="lower center", frameon=False)
    fig.tight_layout(rect=(0, 0.06, 1, 1))


def chart_travel(results: pd.DataFrame, path: Path):
    fig, (top, bottom) = plt.subplots(2, 1, figsize=(12, 7), sharex=True)
    _grouped_bars(top, results, "travel_min")
    top.set_ylabel("Total travel time (min)")
    top.set_title("Travel time per scenario: sequential baseline vs joint optimizer")
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


def chart_summary(results: pd.DataFrame, summary: pd.DataFrame, path: Path):
    """Mean of each summary metric per method (sequential has no travel reduction: it is the reference)."""
    means = summary[(summary["scenario_id"] == "MEAN") & (summary["weights"] != "all")].set_index("weights")
    weight_names = list(means.index)
    labels = ["Sequential"] + [f"Joint\n({w})" for w in weight_names]
    colors = [COLORS[SEQ]] + [COLORS.get(w, "#6250d6") for w in weight_names]
    first = weight_names[0]
    panels = [
        ("Travel-time reduction vs sequential (%)",
         [0.0] + [means.loc[w, "travel_reduction_pct"] for w in weight_names]),
        ("Budget-adherence rate (%)",
         [means.loc[first, "seq_within_budget"] * 100] + [means.loc[w, "joint_within_budget"] * 100
                                                          for w in weight_names]),
        ("Opening-hour conflict rate (%)",
         [means.loc[first, "seq_conflict_rate"] * 100] + [means.loc[w, "joint_conflict_rate"] * 100
                                                          for w in weight_names]),
        ("Places scheduled (mean per trip)",
         [means.loc[first, "seq_places_scheduled"]] + [means.loc[w, "joint_places_scheduled"]
                                                        for w in weight_names]),
    ]
    fig, axes = plt.subplots(2, 2, figsize=(11, 7))
    for ax, (title, values) in zip(axes.flat, panels):
        bars = ax.bar(range(len(labels)), values, 0.6, color=colors)
        ax.bar_label(bars, fmt="%.1f", padding=2, fontsize=9)
        ax.axhline(0, color="#8a8985", linewidth=0.8)
        ax.set_xticks(range(len(labels)), labels)
        ax.set_title(title, fontsize=10)
        low, high = min(0, min(values)), max(values)
        ax.set_ylim(low * 1.2, high * 1.2 if high > 0 else 1)  # all-zero panels still get a sane axis
        if not any(values):
            ax.text(0.5, 0.5, "0 in every plan", transform=ax.transAxes, ha="center", color="#52514e")
    axes.flat[0].set_xticks(range(len(labels)), ["Sequential\n(reference)", *labels[1:]])
    n = summary[(summary["scenario_id"] != "MEAN")]["scenario_id"].nunique()
    fig.suptitle(f"Mean over {n} scenarios: sequential baseline vs joint optimizer")
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


# ---------- Run everything ----------

def run_evaluation(scenarios: Sequence[Scenario],
                   weight_settings: Mapping[str, Mapping[str, float]] = config.EVALUATION_WEIGHT_SETTINGS,
                   out_dir: Path = RESULTS_DIR, cache_dir: Path = config.CACHE_DIR,
                   max_iterations: int = config.JOINT_MAX_ITERATIONS) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run all scenarios, write the CSVs and charts to out_dir, return (results, summary)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = [row for sc in scenarios for row in evaluate_scenario(sc, weight_settings, max_iterations, cache_dir)]
    results = pd.DataFrame(rows)
    summary = summarise(results)
    results.to_csv(out_dir / "results.csv", index=False)
    summary.to_csv(out_dir / "summary.csv", index=False)

    _style()
    chart_travel(results, out_dir / "travel_time.png")
    chart_budget(results, out_dir / "budget_adherence.png")
    chart_summary(results, summary, out_dir / "summary_metrics.png")
    return results, summary


def report(summary: pd.DataFrame, scenarios: Sequence[Scenario]) -> str:
    """Plain-text summary for the console, including every case where joint is not better."""
    short = summary[["scenario_id", "weights", "travel_reduction_pct", "seq_within_budget", "joint_within_budget",
                     "seq_places_scheduled", "joint_places_scheduled", "diff_score_collected",
                     "diff_travel_min_per_place", "diff_wait_min", "verdict"]]
    lines = [short.to_string(index=False), ""]
    not_better = summary[(summary["scenario_id"] != "MEAN") & (summary["verdict"] != "better")]
    lines.append(f"Joint is NOT better in {len(not_better)} of "
                 f"{(summary['scenario_id'] != 'MEAN').sum()} scenario x weight runs:")
    desc = {s.id: s.description for s in scenarios}
    for _, r in not_better.iterrows():
        lines.append(f"  {r['scenario_id']} [{r['weights']}] {r['verdict']}: {desc.get(r['scenario_id'], '')}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scenarios", nargs="*", help="scenario ids to run (default: all)")
    parser.add_argument("--iterations", type=int, default=config.JOINT_MAX_ITERATIONS)
    parser.add_argument("--out-dir", type=Path, default=RESULTS_DIR)
    args = parser.parse_args(argv)

    scenarios = build_scenarios()
    if args.scenarios:
        scenarios = [s for s in scenarios if s.id in set(args.scenarios)]
    _, summary = run_evaluation(scenarios, out_dir=args.out_dir, max_iterations=args.iterations)
    pd.set_option("display.width", 200)
    print(report(summary, scenarios))
    print(f"\nWritten to {args.out_dir}: results.csv, summary.csv, travel_time.png, "
          "budget_adherence.png, summary_metrics.png")


if __name__ == "__main__":
    main()
