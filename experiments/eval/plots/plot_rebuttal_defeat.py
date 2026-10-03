"""反論の評価（eval_rebuttal_defeat）の結果を、設定ターン数を横軸にした折れ線にまとめる.

左: still_valid の平均（低いほど、議論中の反論が最終回答に効いていない）。ログ単位の平均を手法ごとに平均し、
    誤差棒は 95% CI（ログ単位）。
右: still_valid が 0.7 以上（確信をもって「まだ効く」と判定）の反論の割合。

入力は logs/experiment_<日時>/（turns<N>/eval_result/rebuttal_defeat/rebuttal_defeat_comparison.json を読む）。

出力（既定は実験フォルダ直下）:
- rebuttal_defeat.png
- rebuttal_defeat.csv

Usage:
    python -m experiments.eval.plots.plot_rebuttal_defeat logs/experiment_20261002_052448
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
HIGH = 0.7
_TURNS_DIR_RE = re.compile(r"^turns(\d+)$")

Series = dict[str, dict[int, list[float]]]  # 手法 → 設定ターン数 → ログ単位の値


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("experiment_dir", type=Path, help="logs/experiment_<日時>")
    parser.add_argument("--out-dir", type=Path, default=None, help="既定は実験フォルダ直下。")
    return parser.parse_args()


def _mean_ci95(values: list[float]) -> tuple[float, float]:
    if len(values) < 2:
        return (values[0] if values else math.nan), 0.0
    return statistics.mean(values), 1.96 * statistics.stdev(values) / math.sqrt(len(values))


def _collect(experiment_dir: Path) -> tuple[Series, Series]:
    still_valid: Series = {}
    high_rate: Series = {}
    for turns_dir in sorted(experiment_dir.iterdir()):
        match = _TURNS_DIR_RE.match(turns_dir.name)
        path = turns_dir / "eval_result" / "rebuttal_defeat" / "rebuttal_defeat_comparison.json"
        if not match or not path.exists():
            continue
        limit = int(match.group(1))
        detail: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))["detail"]
        for row in detail:
            values = [
                j["scores"]["still_valid"] for j in row["rebuttals"] if j["scores"].get("still_valid") is not None
            ]
            if not values:
                continue
            still_valid.setdefault(row["method"], {}).setdefault(limit, []).append(statistics.mean(values))
            high_rate.setdefault(row["method"], {}).setdefault(limit, []).append(
                sum(v >= HIGH for v in values) / len(values)
            )
    return still_valid, high_rate


def _draw(ax: Any, series: Series, limits: list[int]) -> None:
    methods = [m for m in METHOD_ORDER if m in series]
    spread = 0.9  # 同じ値の手法が重ならないよう、横軸を少しずらして描く
    for index, method in enumerate(methods):
        offset = (index - (len(methods) - 1) / 2) * spread
        xs, means, cis = [], [], []
        for limit in limits:
            values = series[method].get(limit)
            if not values:
                continue
            mean, ci = _mean_ci95(values)
            xs.append(limit + offset)
            means.append(mean)
            cis.append(min(ci, mean))
        ax.errorbar(
            xs,
            means,
            yerr=cis,
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
    still_valid, high_rate = _collect(experiment_dir)
    limits = sorted({limit for per in still_valid.values() for limit in per})
    if not limits:
        raise SystemExit(f"rebuttal_defeat の評価結果が見つかりません: {experiment_dir}")

    fig, axes = plt.subplots(1, 2, figsize=(10.5, 4.6))
    _draw(axes[0], still_valid, limits)
    axes[0].set_title("最終回答に対して反論がまだ効く度合い（低いほど良い）")
    axes[0].set_ylabel("still_valid の平均")
    _draw(axes[1], high_rate, limits)
    axes[1].set_title(f"確信をもって「まだ効く」と判定された反論の割合（≥{HIGH}）")
    axes[1].set_ylabel("割合（低いほど良い）")

    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", ncol=len(labels), frameon=False)
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    out_dir.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_dir / "rebuttal_defeat.png", dpi=160)
    plt.close(fig)

    with (out_dir / "rebuttal_defeat.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["metric", "method", "max_dialogue_turns", "n_logs", "mean", "ci95"])
        for name, series in (("still_valid_mean", still_valid), (f"still_valid_ge_{HIGH}_rate", high_rate)):
            for method in METHOD_ORDER:
                for limit in limits:
                    values = series.get(method, {}).get(limit)
                    if values:
                        mean, ci = _mean_ci95(values)
                        writer.writerow([name, method, limit, len(values), round(mean, 4), round(ci, 4)])
    print(f"Saved: {out_dir / 'rebuttal_defeat.png'}")


if __name__ == "__main__":
    main()
