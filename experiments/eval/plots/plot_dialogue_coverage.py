"""議論全体のカバレッジと、最終回答のカバレッジを手法別に並べて棒グラフにする.

入力は logs/experiment_<日時>/（turns<N>/eval_result/dialogue_coverage/ の JSON を読む）。
eval_dialogue_coverage.py が出す detail（ログごとの項目単位の判定）から、ログ単位の比率を作る。

各設定ターン数ごとに 1 枚のパネルを描く:
- 薄い棒: 議論全体（勝った主張も負けた主張も含む全発話）が扱った項目の割合
- 濃い棒: 最終回答が扱った項目の割合
- 棒の上の数字: retention（議論で扱われた項目のうち、最終回答にも残った割合）

出力（既定は実験フォルダ直下）:
- dialogue_vs_final_coverage.png
- dialogue_vs_final_coverage.csv

Usage:
    python -m experiments.eval.plots.plot_dialogue_coverage logs/experiment_20261002_052448
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
from matplotlib.patches import Rectangle

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
_TURNS_DIR_RE = re.compile(r"^turns(\d+)$")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("experiment_dir", type=Path, help="logs/experiment_<日時>")
    parser.add_argument("--out-dir", type=Path, default=None, help="既定は実験フォルダ直下。")
    return parser.parse_args()


def _mean_ci95(values: list[float]) -> tuple[float, float]:
    if len(values) < 2:
        return (values[0] if values else math.nan), 0.0
    return statistics.mean(values), 1.96 * statistics.stdev(values) / math.sqrt(len(values))


def _collect(experiment_dir: Path) -> dict[int, dict[str, dict[str, list[float]]]]:
    """設定ターン数 → 手法 → {"final": [...], "dialogue": [...]}（ログ単位の比率）."""
    data: dict[int, dict[str, dict[str, list[float]]]] = {}
    for turns_dir in sorted(experiment_dir.iterdir()):
        match = _TURNS_DIR_RE.match(turns_dir.name)
        path = turns_dir / "eval_result" / "dialogue_coverage" / "dialogue_coverage_comparison.json"
        if not match or not path.exists():
            continue
        detail: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))["detail"]
        per_method: dict[str, dict[str, list[float]]] = {}
        for row in detail:
            if not row.get("valid"):
                continue
            entry = per_method.setdefault(row["method"], {"final": [], "dialogue": []})
            entry["final"].append(row["final_covered"] / row["valid"])
            entry["dialogue"].append(row["dialogue_covered"] / row["valid"])
        data[int(match.group(1))] = per_method
    return data


def main() -> None:
    """CLI entrypoint."""
    args = _parse_args()
    experiment_dir = args.experiment_dir.resolve()
    out_dir = (args.out_dir or experiment_dir).resolve()
    data = _collect(experiment_dir)
    if not data:
        raise SystemExit(f"dialogue_coverage の評価結果が見つかりません: {experiment_dir}")

    limits = sorted(data)
    fig, axes = plt.subplots(1, len(limits), figsize=(4.6 * len(limits), 5), sharey=True)
    axes = [axes] if len(limits) == 1 else list(axes)
    rows: list[list[Any]] = []
    width = 0.38
    for ax, limit in zip(axes, limits, strict=True):
        methods = [m for m in METHOD_ORDER if m in data[limit]]
        for index, method in enumerate(methods):
            color = METHOD_COLORS[method]
            dlg_mean, dlg_ci = _mean_ci95(data[limit][method]["dialogue"])
            fin_mean, fin_ci = _mean_ci95(data[limit][method]["final"])
            ax.bar(index - width / 2, dlg_mean, width, yerr=dlg_ci, capsize=3, color=color, alpha=0.35)
            ax.bar(index + width / 2, fin_mean, width, yerr=fin_ci, capsize=3, color=color)
            retention = fin_mean / dlg_mean if dlg_mean else math.nan
            ax.text(index, max(dlg_mean + dlg_ci, fin_mean + fin_ci) + 0.02, f"保持 {retention:.2f}", ha="center", fontsize=8)
            rows.append([limit, method, len(data[limit][method]["final"]), round(dlg_mean, 4), round(fin_mean, 4), round(retention, 4)])
        ax.set_xticks(range(len(methods)))
        ax.set_xticklabels([DISPLAY_NAMES[m] for m in methods], rotation=20)
        ax.set_title(f"設定 {limit} ターン")
        ax.set_ylim(0, 1.12)
        ax.grid(axis="y", alpha=0.3)
    axes[0].set_ylabel("スタンス項目のカバレッジ")
    handles = [
        Rectangle((0, 0), 1, 1, color="#555555", alpha=0.35),
        Rectangle((0, 0), 1, 1, color="#555555"),
    ]
    fig.legend(handles, ["議論全体（負けた主張を含む）", "最終回答"], loc="upper center", ncol=2, frameon=False)
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    out_dir.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_dir / "dialogue_vs_final_coverage.png", dpi=160)
    plt.close(fig)

    with (out_dir / "dialogue_vs_final_coverage.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["max_dialogue_turns", "method", "n", "dialogue_coverage", "final_coverage", "retention"])
        writer.writerows(rows)
    print(f"Saved: {out_dir / 'dialogue_vs_final_coverage.png'}")


if __name__ == "__main__":
    main()
