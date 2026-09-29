r"""SVIをトピック・手法・エージェント別に集計し、棒グラフで可視化する.

前提:
- 入力は eval_svi_final.py が生成した svi_comparison.json。
- 各トピック × 各手法について複数試行（現行実験では5試行）が存在する。
- AG1 / AG2 は混ぜずに別々に集計する。
- SVIの逆転項目は分析時のみ補正する。raw JSON は変更しない。
  - Q3: Instrumental Outcome の逆転項目 -> 8 - score
  - Q5: Self の逆転項目 -> 8 - score

デフォルトでは Instrumental Outcome を可視化する。
必要に応じて --metrics で self / process / relationship / global を追加できる。

Usage:
    python -m experiments.eval.plots.plot_svi_topic_agent

    python -m experiments.eval.plots.plot_svi_topic_agent \
      --input logs/final_gpt54nano_turns10/svi_comparison.json \
      --out-dir logs/final_gpt54nano_turns10/svi_analysis \
      --metrics instrumental

    python -m experiments.eval.plots.plot_svi_topic_agent \
      --metrics instrumental self process relationship global
"""

# ruff: noqa: T201, E402, I001

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

DEFAULT_INPUT = Path("logs/final_gpt54nano_turns10/svi_comparison.json")
DEFAULT_OUT_DIR = Path("logs/final_gpt54nano_turns10/svi_analysis")

METHOD_ORDER = ("free_debate", "mad", "no_schema", "schema")
DISPLAY_NAMES = {
    "free_debate": "Free Debate",
    "mad": "MAD",
    "no_schema": "No Schema",
    "schema": "Schema",
}

METRIC_ITEMS = {
    "instrumental": (1, 2, 3, 4),
    "self": (5, 6, 7, 8),
    "process": (9, 10, 11, 12),
    "relationship": (13, 14, 15, 16),
    "global": tuple(range(1, 17)),
}
REVERSED_ITEMS = {3, 5}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Aggregate SVI by topic, method, and agent. Reverse Q3/Q5 only at analysis time."
        )
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument(
        "--metrics",
        nargs="+",
        choices=tuple(METRIC_ITEMS),
        default=["instrumental"],
        help="Metrics to aggregate/plot. Default: instrumental",
    )
    parser.add_argument(
        "--no-ci",
        action="store_true",
        help="Do not draw 95%% CI error bars.",
    )
    return parser.parse_args()


def _load_input(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    detail = data.get("detail")
    if not isinstance(detail, list):
        raise ValueError(f"Expected list at data['detail']: {path}")
    return detail


def _item_map(items: list[dict[str, Any]]) -> dict[int, float]:
    out: dict[int, float] = {}
    for row in items:
        item = row.get("item")
        score = row.get("score")
        if not isinstance(item, int) or not isinstance(score, (int, float)):
            continue
        out[item] = float(score)
    return out


def _corrected_item_score(item_no: int, score: float) -> float:
    if item_no in REVERSED_ITEMS:
        return 8.0 - score
    return score


def _metric_score(items: list[dict[str, Any]], metric: str) -> float:
    scores = _item_map(items)
    item_nos = METRIC_ITEMS[metric]
    missing = [item for item in item_nos if item not in scores]
    if missing:
        raise ValueError(f"Missing SVI item(s) for {metric}: {missing}")
    corrected = [_corrected_item_score(item, scores[item]) for item in item_nos]
    return sum(corrected) / len(corrected)


def _mean_sd_ci95(values: list[float]) -> tuple[float, float, float]:
    if not values:
        return math.nan, math.nan, math.nan
    mean = statistics.mean(values)
    if len(values) == 1:
        return mean, 0.0, 0.0
    sd = statistics.stdev(values)
    ci95 = 1.96 * sd / math.sqrt(len(values))
    return mean, sd, ci95


def _collect_rows(
    detail: list[dict[str, Any]], metrics: list[str]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    raw_rows: list[dict[str, Any]] = []
    grouped: dict[tuple[str, str, str, str], list[float]] = defaultdict(list)

    for record in detail:
        topic = record.get("topic")
        category = record.get("category")
        method = record.get("method")
        file_name = record.get("file")
        if not isinstance(topic, str) or not isinstance(method, str):
            continue

        for agent_key, agent_label in (("agent1", "AG1"), ("agent2", "AG2")):
            items = record.get(agent_key)
            if not isinstance(items, list):
                continue
            for metric in metrics:
                score = _metric_score(items, metric)
                raw_rows.append(
                    {
                        "topic": topic,
                        "category": category,
                        "method": method,
                        "file": file_name,
                        "agent": agent_label,
                        "metric": metric,
                        "score": score,
                    }
                )
                grouped[(topic, method, agent_label, metric)].append(score)

    summary_rows: list[dict[str, Any]] = []
    for (topic, method, agent, metric), values in sorted(grouped.items()):
        mean, sd, ci95 = _mean_sd_ci95(values)
        summary_rows.append(
            {
                "topic": topic,
                "method": method,
                "agent": agent,
                "metric": metric,
                "mean": mean,
                "sd": sd,
                "ci95": ci95,
                "n": len(values),
            }
        )

    return raw_rows, summary_rows


def _write_csv(rows: list[dict[str, Any]], path: Path, fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _plot_topic_metric(
    summary_rows: list[dict[str, Any]],
    *,
    topic: str,
    metric: str,
    out_path: Path,
    draw_ci: bool,
) -> None:
    rows = [
        row
        for row in summary_rows
        if row["topic"] == topic and row["metric"] == metric
    ]
    lookup = {(row["method"], row["agent"]): row for row in rows}

    methods = [m for m in METHOD_ORDER if (m, "AG1") in lookup or (m, "AG2") in lookup]
    if not methods:
        return

    x = list(range(len(methods)))
    width = 0.36

    ag1_means = [lookup[(m, "AG1")]["mean"] for m in methods]
    ag2_means = [lookup[(m, "AG2")]["mean"] for m in methods]
    ag1_ci = [lookup[(m, "AG1")]["ci95"] for m in methods]
    ag2_ci = [lookup[(m, "AG2")]["ci95"] for m in methods]

    fig, ax = plt.subplots(figsize=(9.2, 5.6))
    error_kw = {"capsize": 4, "elinewidth": 1.1} if draw_ci else None

    ax.bar(
        [v - width / 2 for v in x],
        ag1_means,
        width,
        yerr=ag1_ci if draw_ci else None,
        error_kw=error_kw,
        label="AG1",
    )
    ax.bar(
        [v + width / 2 for v in x],
        ag2_means,
        width,
        yerr=ag2_ci if draw_ci else None,
        error_kw=error_kw,
        label="AG2",
    )

    ax.set_title(f"SVI {metric.title()} by Method and Agent — {topic}", fontsize=13, pad=12)
    ax.set_xlabel("Method")
    ax.set_ylabel("Mean SVI score (1–7)")
    ax.set_ylim(1, 7)
    ax.set_xticks(x)
    ax.set_xticklabels([DISPLAY_NAMES.get(m, m) for m in methods])
    ax.grid(axis="y", alpha=0.25)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False)

    for xpos, method in zip(x, methods, strict=True):
        n1 = lookup[(method, "AG1")]["n"]
        n2 = lookup[(method, "AG2")]["n"]
        if n1 != n2:
            ax.annotate(
                f"n={n1}/{n2}",
                (xpos, 1.03),
                ha="center",
                va="bottom",
                fontsize=8,
            )
        else:
            ax.annotate(
                f"n={n1}",
                (xpos, 1.03),
                ha="center",
                va="bottom",
                fontsize=8,
            )

    fig.tight_layout()
    fig.savefig(out_path, dpi=180, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    """CLI entrypoint."""
    args = _parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    detail = _load_input(args.input)
    raw_rows, summary_rows = _collect_rows(detail, args.metrics)

    raw_csv = args.out_dir / "svi_topic_agent_trial_scores.csv"
    summary_csv = args.out_dir / "svi_topic_agent_summary.csv"
    _write_csv(
        raw_rows,
        raw_csv,
        ["topic", "category", "method", "file", "agent", "metric", "score"],
    )
    _write_csv(
        summary_rows,
        summary_csv,
        ["topic", "method", "agent", "metric", "mean", "sd", "ci95", "n"],
    )

    topics = sorted({row["topic"] for row in summary_rows})
    for metric in args.metrics:
        metric_dir = args.out_dir / metric
        metric_dir.mkdir(parents=True, exist_ok=True)
        for topic in topics:
            safe_topic = topic.replace(" ", "_").replace("/", "_")
            _plot_topic_metric(
                summary_rows,
                topic=topic,
                metric=metric,
                out_path=metric_dir / f"{safe_topic}.png",
                draw_ci=not args.no_ci,
            )

    print(f"Input: {args.input}")
    print(f"Trials CSV: {raw_csv}")
    print(f"Summary CSV: {summary_csv}")
    print(f"Metrics: {', '.join(args.metrics)}")
    print(f"Topics: {len(topics)}")
    print("Reverse-scoring applied only during analysis: Q3 and Q5 -> 8 - score")


if __name__ == "__main__":
    main()
