r"""Plot SVI item-level (Q1-Q16) results by topic and method.

For each topic x method, aggregate repeated trials separately for AG1 and AG2 and
save one PNG containing all 16 SVI items.

By default the plot shows the RAW questionnaire responses, matching the item-level
visualization used during analysis. Q3 and Q5 therefore remain in their original
wording/direction. Pass --correct-reversed to plot analysis-oriented scores where
Q3 and Q5 are transformed as 8 - score.

Example:
    python -m experiments.eval.plots.plot_svi_item_breakdown \
      --input logs/experiment_20260916_020350/eval_result/svi/questionnaire_result/svi_comparison.json \
      --out-dir logs/experiment_20260916_020350/eval_result/svi/questionnaire_result/svi_item_analysis

    python -m experiments.eval.plots.plot_svi_item_breakdown \
      --input logs/experiment_20260916_020350/eval_result/svi/questionnaire_result/svi_comparison.json \
      --out-dir logs/experiment_20260916_020350/eval_result/svi/questionnaire_result/svi_item_analysis_corrected \
      --correct-reversed
"""

# ruff: noqa: T201

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt

plt.rcParams["font.family"] = ["Hiragino Sans", "sans-serif"]

DEFAULT_INPUT = Path("logs/experiment_20260916_020350/eval_result/svi/questionnaire_result/svi_comparison.json")
DEFAULT_OUT_DIR = Path("logs/experiment_20260916_020350/eval_result/svi/questionnaire_result/svi_item_analysis")

METHOD_ORDER = ("free_debate", "mad", "no_schema", "schema")
DISPLAY_NAMES = {
    "free_debate": "Free Debate",
    "mad": "MAD",
    "no_schema": "No Schema",
    "schema": "Schema",
}

SUBSCALES = (
    ("Instrumental", 1, 4),
    ("Self", 5, 8),
    ("Process", 9, 12),
    ("Relationship", 13, 16),
)
REVERSED_ITEMS = {3, 5}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plot SVI Q1-Q16 five-run means for each topic x method."
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument(
        "--correct-reversed",
        action="store_true",
        help="Apply Q3/Q5 reverse scoring (8-score) before aggregation.",
    )
    parser.add_argument(
        "--no-ci",
        action="store_true",
        help="Do not draw 95%% CI error bars.",
    )
    return parser.parse_args()


def _load_detail(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    detail = data.get("detail")
    if not isinstance(detail, list):
        raise ValueError(f"Expected list at data['detail']: {path}")
    return detail


def _score(item_no: int, raw_score: float, *, correct_reversed: bool) -> float:
    if correct_reversed and item_no in REVERSED_ITEMS:
        return 8.0 - raw_score
    return raw_score


def _collect_trial_rows(
    detail: list[dict[str, Any]],
    *,
    correct_reversed: bool,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    for record in detail:
        topic = record.get("topic")
        category = record.get("category")
        method = record.get("method")
        file_name = record.get("file")
        if not isinstance(topic, str) or not isinstance(method, str):
            continue

        for agent_key, agent_label in (("agent1", "AG1"), ("agent2", "AG2")):
            responses = record.get(agent_key)
            if not isinstance(responses, list):
                continue

            for response in responses:
                item = response.get("item")
                raw = response.get("score")
                if not isinstance(item, int) or not isinstance(raw, (int, float)):
                    continue
                rows.append(
                    {
                        "topic": topic,
                        "category": category,
                        "method": method,
                        "file": file_name,
                        "agent": agent_label,
                        "item": item,
                        "raw_score": float(raw),
                        "score": _score(
                            item,
                            float(raw),
                            correct_reversed=correct_reversed,
                        ),
                    }
                )
    return rows


def _mean_sd_ci95(values: list[float]) -> tuple[float, float, float]:
    if not values:
        return math.nan, math.nan, math.nan
    mean = statistics.mean(values)
    if len(values) == 1:
        return mean, 0.0, 0.0
    sd = statistics.stdev(values)
    ci95 = 1.96 * sd / math.sqrt(len(values))
    return mean, sd, ci95


def _summarize(
    trial_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str, int], list[float]] = defaultdict(list)
    for row in trial_rows:
        grouped[
            (
                str(row["topic"]),
                str(row["method"]),
                str(row["agent"]),
                int(row["item"]),
            )
        ].append(float(row["score"]))

    summary: list[dict[str, Any]] = []
    for (topic, method, agent, item), values in sorted(grouped.items()):
        mean, sd, ci95 = _mean_sd_ci95(values)
        summary.append(
            {
                "topic": topic,
                "method": method,
                "agent": agent,
                "item": item,
                "mean": mean,
                "sd": sd,
                "ci95": ci95,
                "n": len(values),
            }
        )
    return summary


def _write_csv(rows: list[dict[str, Any]], path: Path, fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _plot_topic_method(
    summary: list[dict[str, Any]],
    *,
    topic: str,
    method: str,
    out_path: Path,
    draw_ci: bool,
    corrected: bool,
) -> None:
    rows = [
        row
        for row in summary
        if row["topic"] == topic and row["method"] == method
    ]
    lookup = {(row["agent"], row["item"]): row for row in rows}
    if not rows:
        return

    items = list(range(1, 17))
    x = list(range(len(items)))
    width = 0.36

    ag1_means = [lookup[("AG1", item)]["mean"] for item in items]
    ag2_means = [lookup[("AG2", item)]["mean"] for item in items]
    ag1_ci = [lookup[("AG1", item)]["ci95"] for item in items]
    ag2_ci = [lookup[("AG2", item)]["ci95"] for item in items]

    fig, ax = plt.subplots(figsize=(15.5, 6.8))
    error_kw = {"capsize": 3, "elinewidth": 1.0} if draw_ci else None

    bars1 = ax.bar(
        [v - width / 2 for v in x],
        ag1_means,
        width,
        yerr=ag1_ci if draw_ci else None,
        error_kw=error_kw,
        label="AG1",
    )
    bars2 = ax.bar(
        [v + width / 2 for v in x],
        ag2_means,
        width,
        yerr=ag2_ci if draw_ci else None,
        error_kw=error_kw,
        label="AG2",
    )

    for bars, values in ((bars1, ag1_means), (bars2, ag2_means)):
        for bar, value in zip(bars, values, strict=True):
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                min(value + 0.08, 6.9),
                f"{value:.1f}",
                ha="center",
                va="bottom",
                fontsize=8,
            )

    for boundary in (3.5, 7.5, 11.5):
        ax.axvline(boundary, linestyle="--", linewidth=1, alpha=0.45)

    for label, first, last in SUBSCALES:
        center = ((first - 1) + (last - 1)) / 2
        ax.text(
            center,
            7.22,
            label,
            ha="center",
            va="bottom",
            fontsize=10,
            clip_on=False,
        )

    scoring_label = "reverse-corrected Q3/Q5" if corrected else "raw item scores"
    method_name = DISPLAY_NAMES.get(method, method)
    ax.set_title(
        f"SVI item-level scores — {topic} / {method_name}\n"
        f"5-trial mean by agent ({scoring_label})",
        fontsize=13,
        pad=28,
    )
    ax.set_xlabel("SVI item")
    ax.set_ylabel("Mean score (1–7)")
    ax.set_ylim(1, 7)
    ax.set_xticks(x)
    ax.set_xticklabels([f"Q{item}" for item in items])
    ax.grid(axis="y", alpha=0.25)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, ncol=2)

    n_values = sorted({int(row["n"]) for row in rows})
    n_text = "/".join(str(n) for n in n_values)
    ax.text(
        1.0,
        -0.13,
        f"n={n_text} trials per item/agent",
        transform=ax.transAxes,
        ha="right",
        va="top",
        fontsize=9,
    )

    if not corrected:
        ax.text(
            0.0,
            -0.13,
            "Note: Q3 and Q5 are reverse-keyed items; raw responses are shown.",
            transform=ax.transAxes,
            ha="left",
            va="top",
            fontsize=9,
        )

    fig.tight_layout()
    fig.savefig(out_path, dpi=220, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    """Load SVI detail results and write the item-level breakdown plots."""
    args = _parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    detail = _load_detail(args.input)
    trial_rows = _collect_trial_rows(
        detail,
        correct_reversed=args.correct_reversed,
    )
    summary = _summarize(trial_rows)

    suffix = "corrected" if args.correct_reversed else "raw"
    trial_csv = args.out_dir / f"svi_item_trial_scores_{suffix}.csv"
    summary_csv = args.out_dir / f"svi_item_summary_{suffix}.csv"

    _write_csv(
        trial_rows,
        trial_csv,
        [
            "topic",
            "category",
            "method",
            "file",
            "agent",
            "item",
            "raw_score",
            "score",
        ],
    )
    _write_csv(
        summary,
        summary_csv,
        ["topic", "method", "agent", "item", "mean", "sd", "ci95", "n"],
    )

    topics = sorted({str(row["topic"]) for row in summary})
    methods_present = {str(row["method"]) for row in summary}
    methods = [m for m in METHOD_ORDER if m in methods_present]

    png_count = 0
    for topic in topics:
        topic_dir = args.out_dir / topic.replace(" ", "_").replace("/", "_")
        topic_dir.mkdir(parents=True, exist_ok=True)
        for method in methods:
            if not any(
                row["topic"] == topic and row["method"] == method
                for row in summary
            ):
                continue
            out_path = topic_dir / f"{method}_{suffix}.png"
            _plot_topic_method(
                summary,
                topic=topic,
                method=method,
                out_path=out_path,
                draw_ci=not args.no_ci,
                corrected=args.correct_reversed,
            )
            png_count += 1

    print(f"Input: {args.input}")
    print(f"Output directory: {args.out_dir}")
    print(f"Trial CSV: {trial_csv}")
    print(f"Summary CSV: {summary_csv}")
    print(f"PNG files: {png_count}")
    print(f"Scoring: {'Q3/Q5 reverse-corrected' if args.correct_reversed else 'raw'}")


if __name__ == "__main__":
    main()
