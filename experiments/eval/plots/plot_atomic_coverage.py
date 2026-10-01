"""atomic coverage の評価結果を手法別・トピック別の棒グラフにする.

入力は eval_atomic_coverage_final.py が出す atomic_coverage_comparison.json。
atomic_ratio（立場を分解した原子的主張のうち最終回答がカバーした割合）を使う。

出力（--out-dir）:
- atomic_coverage_by_method.png : 手法別の平均（誤差棒は 95% CI、ログ単位）
- atomic_coverage_by_topic.png  : トピック × 手法のグループ棒グラフ（5 試行平均、95% CI）
- atomic_coverage_summary.csv   : 上記の元データ

Usage:
    python -m experiments.eval.plots.plot_atomic_coverage
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

DEFAULT_INPUT = Path(
    "logs/experiment_20260916_020350/eval_result/atomic_coverage/atomic_coverage_comparison.json"
)
DEFAULT_OUT_DIR = Path("logs/experiment_20260916_020350/eval_result/atomic_coverage")

METHOD_ORDER = ("free_debate", "mad", "no_schema", "schema")
DISPLAY_NAMES = {
    "free_debate": "Free Debate",
    "mad": "MAD",
    "no_schema": "No Schema",
    "schema": "Schema",
}
METHOD_COLORS = {
    "free_debate": "#7f7f7f",
    "mad": "#9467bd",
    "no_schema": "#ff7f0e",
    "schema": "#1f77b4",
}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plot atomic coverage by method and topic."
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument(
        "--no-ci", action="store_true", help="Do not draw 95%% CI error bars."
    )
    return parser.parse_args()


def _mean_ci95(values: list[float]) -> tuple[float, float]:
    if not values:
        return math.nan, 0.0
    if len(values) < 2:
        return values[0], 0.0
    return statistics.mean(values), 1.96 * statistics.stdev(values) / math.sqrt(
        len(values)
    )


def _collect(
    detail: list[dict[str, Any]],
) -> tuple[dict[str, list[float]], dict[str, dict[str, list[float]]]]:
    """手法 → ratio のリスト、トピック → 手法 → ratio のリスト."""
    by_method: dict[str, list[float]] = defaultdict(list)
    by_topic: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for row in detail:
        ratio = row.get("atomic_ratio")
        if not isinstance(ratio, (int, float)):
            continue
        by_method[row["method"]].append(float(ratio))
        by_topic[row["topic"]][row["method"]].append(float(ratio))
    return by_method, by_topic


def _plot_by_method(
    by_method: dict[str, list[float]], path: Path, show_ci: bool
) -> None:
    methods = [m for m in METHOD_ORDER if m in by_method]
    stats = [_mean_ci95(by_method[m]) for m in methods]
    fig, ax = plt.subplots(figsize=(6.5, 5))
    bars = ax.bar(
        [DISPLAY_NAMES[m] for m in methods],
        [mean for mean, _ in stats],
        yerr=[ci for _, ci in stats] if show_ci else None,
        capsize=4,
        color=[METHOD_COLORS[m] for m in methods],
    )
    for bar, (mean, ci) in zip(bars, stats, strict=True):
        ax.annotate(
            f"{mean:.2f}",
            (bar.get_x() + bar.get_width() / 2, mean + (ci if show_ci else 0)),
            textcoords="offset points",
            xytext=(0, 4),
            ha="center",
            fontsize=9,
        )
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("Atomic coverage (covered / total)")
    ax.set_title("Atomic coverage by method", fontsize=12, pad=10)
    ax.grid(axis="y", alpha=0.3)
    ax.spines[["top", "right"]].set_visible(False)
    n = len(by_method[methods[0]]) if methods else 0
    ax.text(
        0,
        -0.12,
        f"mean over logs (n={n} per method)" + ("; 95% CI" if show_ci else ""),
        transform=ax.transAxes,
        fontsize=8,
        color="#555",
    )
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)


def _plot_by_topic(
    by_topic: dict[str, dict[str, list[float]]], path: Path, show_ci: bool
) -> None:
    topics = sorted(by_topic)
    methods = [m for m in METHOD_ORDER if any(m in by_topic[t] for t in topics)]
    width = 0.8 / max(len(methods), 1)
    fig, ax = plt.subplots(figsize=(max(8.0, 1.8 * len(topics)), 5))
    for i, method in enumerate(methods):
        stats = [_mean_ci95(by_topic[t].get(method, [])) for t in topics]
        xs = [j + (i - (len(methods) - 1) / 2) * width for j in range(len(topics))]
        ax.bar(
            xs,
            [mean for mean, _ in stats],
            width=width,
            yerr=[ci for _, ci in stats] if show_ci else None,
            capsize=2,
            color=METHOD_COLORS[method],
            label=DISPLAY_NAMES[method],
        )
    ax.set_xticks(range(len(topics)))
    ax.set_xticklabels([t.replace("_", " ") for t in topics], rotation=20, ha="right")
    ax.set_ylim(0, 1.25)
    ax.set_ylabel("Atomic coverage (covered / total)")
    ax.set_title("Atomic coverage by topic and method", fontsize=12, pad=10)
    ax.grid(axis="y", alpha=0.3)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(
        frameon=False, ncol=len(methods), loc="upper center", bbox_to_anchor=(0.5, 1.0)
    )
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)


def _write_csv(
    by_method: dict[str, list[float]],
    by_topic: dict[str, dict[str, list[float]]],
    path: Path,
) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["topic", "method", "n", "mean", "ci95"])
        for method in METHOD_ORDER:
            if method in by_method:
                mean, ci = _mean_ci95(by_method[method])
                writer.writerow(
                    ["ALL", method, len(by_method[method]), f"{mean:.4f}", f"{ci:.4f}"]
                )
        for topic in sorted(by_topic):
            for method in METHOD_ORDER:
                if method in by_topic[topic]:
                    vals = by_topic[topic][method]
                    mean, ci = _mean_ci95(vals)
                    writer.writerow(
                        [topic, method, len(vals), f"{mean:.4f}", f"{ci:.4f}"]
                    )


def main() -> None:
    """CLI entrypoint."""
    args = _parse_args()
    detail = json.loads(args.input.read_text(encoding="utf-8"))["detail"]
    by_method, by_topic = _collect(detail)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    show_ci = not args.no_ci
    _plot_by_method(by_method, args.out_dir / "atomic_coverage_by_method.png", show_ci)
    _plot_by_topic(by_topic, args.out_dir / "atomic_coverage_by_topic.png", show_ci)
    _write_csv(by_method, by_topic, args.out_dir / "atomic_coverage_summary.csv")

    print(f"Input: {args.input}")
    print(f"Output directory: {args.out_dir}")
    for method in METHOD_ORDER:
        if method in by_method:
            print(
                f"{method:12s} mean={statistics.mean(by_method[method]):.3f} n={len(by_method[method])}"
            )


if __name__ == "__main__":
    main()
