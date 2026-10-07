r"""SVI Instrumental Outcome から合意スコア C_k を計算し、手法別に可視化する.

合意スコア:
    C_k = (A + B) / 2 - k * |A - B|

A, B は AG1 / AG2 の同一項目のスコア。ペナルティ重み k が大きいほど、2 者の評価差が大きい
手法のスコアが下がる。

計算手順:
1. 各ログ・Instrumental Outcome の 4 項目（Q1-Q4）それぞれで C_k を計算する。
   逆転項目 Q3 は分析時のみ 8 - score に補正する（raw JSON は変更しない）。
2. 4 項目の C_k を平均してログ単位のスコアにする。
3. 手法ごとにログ間で平均する（誤差棒は 95% CI）。

出力（--out-dir）:
- svi_consensus_k_lines.png : k（横軸）× 合意スコア（縦軸）の折れ線。全手法を 1 図に重ねる
- svi_score_gap_bar.png     : 評価スコア差 |A - B| の平均（4 項目 × 全ログ）の手法別棒グラフ
- svi_consensus_summary.csv : 上記 2 図の元データ

Usage:
    python -m experiments.eval.plots.plot_svi_consensus_score \
      --input logs/experiment_20260916_020350/eval_result/svi/questionnaire_result/svi_comparison.json \
      --out-dir logs/experiment_20260916_020350/eval_result/svi/consensus
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
    "logs/experiment_20260916_020350/eval_result/svi/questionnaire_result/svi_comparison.json"
)
DEFAULT_OUT_DIR = Path("logs/experiment_20260916_020350/eval_result/svi/consensus")

METHOD_ORDER = ("free_debate", "mad", "mad_synthesis", "no_schema", "schema")
DISPLAY_NAMES = {
    "free_debate": "Free Debate",
    "mad": "MAD",
    "mad_synthesis": "MAD + Synthesis",
    "no_schema": "No Schema",
    "schema": "Schema",
}
METHOD_COLORS = {
    "free_debate": "#7f7f7f",
    "mad": "#9467bd",
    "mad_synthesis": "#c49c94",
    "no_schema": "#ff7f0e",
    "schema": "#1f77b4",
}
INSTRUMENTAL_ITEMS = (1, 2, 3, 4)
REVERSED_ITEMS = {3, 5}
DEFAULT_KS = (0.0, 0.1, 0.25, 0.5)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plot SVI consensus score C_k = (A+B)/2 - k|A-B| (Instrumental Outcome)."
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--ks", type=float, nargs="+", default=list(DEFAULT_KS))
    parser.add_argument(
        "--no-ci", action="store_true", help="Do not draw 95%% CI error bars."
    )
    return parser.parse_args()


def _item_scores(items: list[dict[str, Any]]) -> dict[int, float]:
    """項目番号 → 補正後スコア（Q3 は 8 - score）."""
    scores: dict[int, float] = {}
    for row in items:
        item, score = row.get("item"), row.get("score")
        if isinstance(item, int) and isinstance(score, (int, float)):
            scores[item] = (
                8.0 - float(score) if item in REVERSED_ITEMS else float(score)
            )
    missing = [i for i in INSTRUMENTAL_ITEMS if i not in scores]
    if missing:
        raise ValueError(f"Missing SVI item(s): {missing}")
    return scores


def _mean_ci95(values: list[float]) -> tuple[float, float]:
    if len(values) < 2:
        return (values[0] if values else math.nan), 0.0
    return statistics.mean(values), 1.96 * statistics.stdev(values) / math.sqrt(
        len(values)
    )


def _consensus(a: float, b: float, k: float) -> float:
    return (a + b) / 2 - k * abs(a - b)


def _collect(
    detail: list[dict[str, Any]], ks: list[float]
) -> tuple[dict[str, dict[float, list[float]]], dict[str, list[float]]]:
    """手法 → k → ログ単位の C_k のリスト、手法 → 項目単位の |A-B| のリスト."""
    consensus: dict[str, dict[float, list[float]]] = defaultdict(
        lambda: defaultdict(list)
    )
    gaps: dict[str, list[float]] = defaultdict(list)
    for entry in detail:
        method = entry["method"]
        a = _item_scores(entry["agent1"])
        b = _item_scores(entry["agent2"])
        for k in ks:
            per_item = [_consensus(a[i], b[i], k) for i in INSTRUMENTAL_ITEMS]
            consensus[method][k].append(sum(per_item) / len(per_item))
        gaps[method].extend(abs(a[i] - b[i]) for i in INSTRUMENTAL_ITEMS)
    return consensus, gaps


def _plot_lines(
    consensus: dict[str, dict[float, list[float]]],
    ks: list[float],
    path: Path,
    show_ci: bool,
) -> None:
    fig, ax = plt.subplots(figsize=(7.5, 5))
    for method in METHOD_ORDER:
        if method not in consensus:
            continue
        stats = [_mean_ci95(consensus[method][k]) for k in ks]
        means = [m for m, _ in stats]
        ax.errorbar(
            ks,
            means,
            yerr=[c for _, c in stats] if show_ci else None,
            marker="o",
            capsize=3 if show_ci else 0,
            linewidth=2,
            color=METHOD_COLORS[method],
            label=DISPLAY_NAMES[method],
        )
        ax.annotate(
            f"{means[-1]:.2f}",
            (ks[-1], means[-1]),
            textcoords="offset points",
            xytext=(6, 0),
            fontsize=8,
            color=METHOD_COLORS[method],
            va="center",
        )
    ax.set_xticks(ks)
    ax.set_xlabel("Penalty weight k")
    ax.set_ylabel("Consensus score $C_k$")
    ax.set_title(
        r"SVI Instrumental Outcome consensus score  $C_k=(A+B)/2-k|A-B|$",
        fontsize=12,
        pad=10,
    )
    ax.grid(axis="y", alpha=0.3)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False)
    ax.text(
        0,
        -0.14,
        "Q1-Q4 mean (Q3 reverse-corrected); mean over logs"
        + (", 95% CI" if show_ci else ""),
        transform=ax.transAxes,
        fontsize=8,
        color="#555",
    )
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)


def _plot_gap_bar(gaps: dict[str, list[float]], path: Path, show_ci: bool) -> None:
    methods = [m for m in METHOD_ORDER if m in gaps]
    stats = [_mean_ci95(gaps[m]) for m in methods]
    fig, ax = plt.subplots(figsize=(6.5, 5))
    bars = ax.bar(
        [DISPLAY_NAMES[m] for m in methods],
        [m for m, _ in stats],
        yerr=[c for _, c in stats] if show_ci else None,
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
    ax.set_ylabel("Mean |AG1 − AG2| score gap")
    ax.set_title(
        "SVI Instrumental Outcome: mean score gap between agents", fontsize=12, pad=10
    )
    ax.grid(axis="y", alpha=0.3)
    ax.spines[["top", "right"]].set_visible(False)
    ax.text(
        0,
        -0.12,
        "Q1-Q4 × all logs (Q3 reverse-corrected)" + ("; 95% CI" if show_ci else ""),
        transform=ax.transAxes,
        fontsize=8,
        color="#555",
    )
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)


def _write_csv(
    consensus: dict[str, dict[float, list[float]]],
    gaps: dict[str, list[float]],
    ks: list[float],
    path: Path,
) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["method", "metric", "k", "n", "mean", "ci95"])
        for method in METHOD_ORDER:
            if method not in consensus:
                continue
            for k in ks:
                mean, ci = _mean_ci95(consensus[method][k])
                writer.writerow(
                    [
                        method,
                        "consensus_Ck",
                        k,
                        len(consensus[method][k]),
                        f"{mean:.4f}",
                        f"{ci:.4f}",
                    ]
                )
            mean, ci = _mean_ci95(gaps[method])
            writer.writerow(
                [method, "abs_gap", "", len(gaps[method]), f"{mean:.4f}", f"{ci:.4f}"]
            )


def main() -> None:
    """CLI entrypoint."""
    args = _parse_args()
    detail = json.loads(args.input.read_text(encoding="utf-8"))["detail"]
    ks = sorted(args.ks)
    consensus, gaps = _collect(detail, ks)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    show_ci = not args.no_ci
    _plot_lines(consensus, ks, args.out_dir / "svi_consensus_k_lines.png", show_ci)
    _plot_gap_bar(gaps, args.out_dir / "svi_score_gap_bar.png", show_ci)
    _write_csv(consensus, gaps, ks, args.out_dir / "svi_consensus_summary.csv")

    print(f"Input: {args.input}")
    print(f"Output directory: {args.out_dir}")
    for method in METHOD_ORDER:
        if method in consensus:
            row = " ".join(
                f"k={k:g}:{statistics.mean(consensus[method][k]):.3f}" for k in ks
            )
            print(f"{method:12s} {row}  gap={statistics.mean(gaps[method]):.3f}")


if __name__ == "__main__":
    main()
