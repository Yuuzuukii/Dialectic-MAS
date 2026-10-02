"""coverage・SVI 合意スコア・使用ターン数を、設定ターン数を横軸にした 1 枚の図にまとめる.

左: 最終回答の atomic coverage、中: SVI 合意スコア C_k（Instrumental Outcome、既定 k=0.5）、
右: 実際に使った対話ターン数（破線 y = x が上限）。点は手法ごとの平均、誤差棒は 95% CI。

入力は logs/experiment_<日時>/（turns<N>/eval_result と turns<N>/raw_dialogue を読む）。

出力（既定は実験フォルダ直下）:
- summary.png
- summary.csv

Usage:
    python -m experiments.eval.plots.plot_summary logs/experiment_20261002_052448
"""

# ruff: noqa: T201

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import statistics
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt

plt.rcParams["font.family"] = ["Hiragino Sans", "sans-serif"]

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
INSTRUMENTAL_ITEMS = (1, 2, 3, 4)
REVERSED_ITEMS = {3, 5}
_TURNS_DIR_RE = re.compile(r"^turns(\d+)$")

Series = dict[str, dict[int, list[float]]]  # 手法 → 設定ターン数 → ログ単位の値


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("experiment_dir", type=Path, help="logs/experiment_<日時>")
    parser.add_argument("--k", type=float, default=0.5, help="合意スコアのペナルティ重み。")
    parser.add_argument("--out-dir", type=Path, default=None, help="既定は実験フォルダ直下。")
    return parser.parse_args()


def _mean_ci95(values: list[float], upper: float | None = None) -> tuple[float, float, float]:
    """(平均, 下側の誤差, 上側の誤差). upper を渡すと上側を上限で止める."""
    if len(values) < 2:
        mean = values[0] if values else math.nan
        return mean, 0.0, 0.0
    mean = statistics.mean(values)
    ci = 1.96 * statistics.stdev(values) / math.sqrt(len(values))
    up = ci if upper is None else max(0.0, min(ci, upper - mean))
    return mean, min(ci, mean), up


def _item_scores(items: list[dict[str, Any]]) -> dict[int, float]:
    scores: dict[int, float] = {}
    for row in items:
        item, score = row.get("item"), row.get("score")
        if isinstance(item, int) and isinstance(score, (int, float)):
            scores[item] = 8.0 - float(score) if item in REVERSED_ITEMS else float(score)
    return scores


def _collect(experiment_dir: Path, k: float) -> tuple[Series, Series, Series]:
    coverage: Series = {}
    svi: Series = {}
    used: Series = {}
    for turns_dir in sorted(experiment_dir.iterdir()):
        match = _TURNS_DIR_RE.match(turns_dir.name)
        if not match or not turns_dir.is_dir():
            continue
        limit = int(match.group(1))
        cov_path = turns_dir / "eval_result" / "atomic_coverage" / "atomic_coverage_comparison.json"
        if cov_path.exists():
            for row in json.loads(cov_path.read_text(encoding="utf-8"))["detail"]:
                ratio = row.get("atomic_ratio")
                if isinstance(ratio, (int, float)):
                    coverage.setdefault(row["method"], {}).setdefault(limit, []).append(float(ratio))
        svi_path = turns_dir / "eval_result" / "svi" / "questionnaire_result" / "svi_comparison.json"
        if svi_path.exists():
            for row in json.loads(svi_path.read_text(encoding="utf-8"))["detail"]:
                a, b = _item_scores(row["agent1"]), _item_scores(row["agent2"])
                if not all(i in a and i in b for i in INSTRUMENTAL_ITEMS):
                    continue
                per_item = [(a[i] + b[i]) / 2 - k * abs(a[i] - b[i]) for i in INSTRUMENTAL_ITEMS]
                svi.setdefault(row["method"], {}).setdefault(limit, []).append(sum(per_item) / len(per_item))
        for path in sorted((turns_dir / "raw_dialogue").glob("*/*/*.json")):
            log = json.loads(path.read_text(encoding="utf-8"))
            if log.get("method") in METHOD_ORDER:
                used.setdefault(log["method"], {}).setdefault(limit, []).append(float(len(log.get("dialogue_history", []))))
    return coverage, svi, used


def _draw(ax: Any, series: Series, limits: list[int], *, cap_at_limit: bool = False) -> None:
    methods = [m for m in METHOD_ORDER if m in series]
    spread = 0.9  # 同じ値の手法が重ならないよう、横軸を少しずらして描く
    for index, method in enumerate(methods):
        offset = (index - (len(methods) - 1) / 2) * spread
        xs, means, lows, ups = [], [], [], []
        for limit in limits:
            values = series[method].get(limit)
            if not values:
                continue
            mean, low, up = _mean_ci95(values, upper=float(limit) if cap_at_limit else None)
            xs.append(limit + offset)
            means.append(mean)
            lows.append(low)
            ups.append(up)
        ax.errorbar(
            xs,
            means,
            yerr=[lows, ups],
            marker="o",
            linewidth=2,
            capsize=3,
            color=METHOD_COLORS[method],
            label=DISPLAY_NAMES[method],
        )
    ax.set_xticks(limits)
    ax.set_xlabel("設定ターン数")
    ax.grid(alpha=0.3)


def main() -> None:
    """CLI entrypoint."""
    args = _parse_args()
    experiment_dir = args.experiment_dir.resolve()
    out_dir = (args.out_dir or experiment_dir).resolve()
    coverage, svi, used = _collect(experiment_dir, args.k)
    limits = sorted({limit for series in (coverage, svi, used) for per in series.values() for limit in per})
    if not limits:
        raise SystemExit(f"turns<N> の評価結果が見つかりません: {experiment_dir}")

    fig, axes = plt.subplots(1, 3, figsize=(15, 4.6))
    _draw(axes[0], coverage, limits)
    axes[0].set_title("最終回答の coverage")
    axes[0].set_ylabel("atomic coverage")
    axes[0].set_ylim(0.3, 1.0)

    _draw(axes[1], svi, limits)
    axes[1].set_title(f"SVI 合意スコア（C_k, k={args.k}）")
    axes[1].set_ylabel("合意スコア（高いほど良い）")

    top = max(limits)
    axes[2].plot([0, top + 5], [0, top + 5], color="#bbbbbb", linestyle="--", linewidth=1.2, label="上限（y = x）")
    _draw(axes[2], used, limits, cap_at_limit=True)
    axes[2].set_title("使用ターン数")
    axes[2].set_ylabel("実際に使ったターン数")
    axes[2].set_xlim(min(limits) - 4, top + 4)
    axes[2].set_ylim(min(limits) - 4, top + 4)

    handles, labels = axes[2].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", ncol=len(labels), frameon=False)
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    out_dir.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_dir / "summary.png", dpi=160)
    plt.close(fig)

    with (out_dir / "summary.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["metric", "method", "max_dialogue_turns", "n", "mean", "ci95"])
        for name, series in (("coverage", coverage), ("svi_consensus", svi), ("turns_used", used)):
            for method in METHOD_ORDER:
                for limit in limits:
                    values = series.get(method, {}).get(limit)
                    if values:
                        mean, low, _ = _mean_ci95(values)
                        writer.writerow([name, method, limit, len(values), round(mean, 4), round(low, 4)])
    print(f"Saved: {out_dir / 'summary.png'}")


if __name__ == "__main__":
    main()
