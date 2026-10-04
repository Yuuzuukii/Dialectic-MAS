"""SVI 合意スコアを、評価器（nano / mini）ごとに並べて可視化する.

入力は logs/experiment_<日時>/ 。turns<N>/eval_result/<サブフォルダ>/questionnaire_result/
svi_comparison.json を読む（既定: svi = nano、svi_mini = mini）。

出力（既定は実験フォルダ直下）:
- svi_by_turns.png : 設定ターン数ごとの合意スコア C_k（左 nano・右 mini、縦軸は共通、95% CI）
- svi_k_sweep.png  : ペナルティ重み k を 0〜1 で変えたときの C_k（左 nano・右 mini、全設定合算）
- svi_pooled.png   : 全設定を合算した C_k と、AG1・AG2 の満足度の差 |A-B|（薄い棒 nano・濃い棒 mini）
- svi_by_evaluator.csv

C_k = (A+B)/2 - k|A-B|（Instrumental Outcome の項目 1〜4、項目 3 は逆転、既定 k=0.5）。

Usage:
    python -m experiments.eval.plots.plot_svi_evaluators logs/experiment_20261004_165642
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
DISPLAY_NAMES = {"free_debate": "Free Debate", "mad": "MAD", "no_schema": "No Schema", "schema": "Schema"}
METHOD_COLORS = {"free_debate": "#7f7f7f", "mad": "#9467bd", "no_schema": "#ff7f0e", "schema": "#1f77b4"}
INSTRUMENTAL_ITEMS = (1, 2, 3, 4)
REVERSED_ITEMS = {3, 5}
_TURNS_DIR_RE = re.compile(r"^turns(\d+)$")

# 評価器ごとの (表示名, eval_result 内のサブフォルダ)
EVALUATORS = (("nano", "svi"), ("mini", "svi_mini"))

# 手法 → 設定ターン数 → ログごとの (平均点 (A+B)/2, 差 |A-B|)。C_k = 平均点 - k * 差 なので k は後から選べる。
Scores = dict[str, dict[int, list[tuple[float, float]]]]
K_SWEEP = (0.0, 0.1, 0.25, 0.5, 0.75, 1.0)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("experiment_dir", type=Path, help="logs/experiment_<日時>")
    parser.add_argument("--k", type=float, default=0.5, help="合意スコアのペナルティ重み。")
    parser.add_argument("--out-dir", type=Path, default=None, help="既定は実験フォルダ直下。")
    return parser.parse_args()


def _item_scores(items: list[dict[str, Any]]) -> dict[int, float]:
    scores: dict[int, float] = {}
    for row in items:
        item, score = row.get("item"), row.get("score")
        if isinstance(item, int) and isinstance(score, (int, float)):
            scores[item] = 8.0 - float(score) if item in REVERSED_ITEMS else float(score)
    return scores


def _collect(experiment_dir: Path, subdir: str) -> Scores:
    scores: Scores = {}
    for turns_dir in sorted(experiment_dir.iterdir()):
        match = _TURNS_DIR_RE.match(turns_dir.name)
        path = turns_dir / "eval_result" / subdir / "questionnaire_result" / "svi_comparison.json"
        if not match or not path.exists():
            continue
        limit = int(match.group(1))
        for row in json.loads(path.read_text(encoding="utf-8"))["detail"]:
            a, b = _item_scores(row["agent1"]), _item_scores(row["agent2"])
            if not all(i in a and i in b for i in INSTRUMENTAL_ITEMS):
                continue
            level = statistics.mean((a[i] + b[i]) / 2 for i in INSTRUMENTAL_ITEMS)
            gap = statistics.mean(abs(a[i] - b[i]) for i in INSTRUMENTAL_ITEMS)
            scores.setdefault(row["method"], {}).setdefault(limit, []).append((level, gap))
    return scores


def _mean_ci95(values: list[float]) -> tuple[float, float]:
    if len(values) < 2:
        return (values[0] if values else math.nan), 0.0
    return statistics.mean(values), 1.96 * statistics.stdev(values) / math.sqrt(len(values))


def _ck(pair: tuple[float, float], k: float) -> float:
    return pair[0] - k * pair[1]


def _pooled_ck(scores: Scores, method: str, k: float) -> list[float]:
    return [_ck(pair, k) for per in scores.get(method, {}).values() for pair in per]


def _pooled_gap(scores: Scores, method: str) -> list[float]:
    return [pair[1] for per in scores.get(method, {}).values() for pair in per]


def _draw_lines(ax: Any, scores: Scores, limits: list[int], k: float) -> None:
    methods = [m for m in METHOD_ORDER if m in scores]
    spread = 0.9  # 同じ値の手法が重ならないよう、横軸を少しずらして描く
    for index, method in enumerate(methods):
        offset = (index - (len(methods) - 1) / 2) * spread
        xs, means, cis = [], [], []
        for limit in limits:
            values = [_ck(pair, k) for pair in scores[method].get(limit, [])]
            if not values:
                continue
            mean, ci = _mean_ci95(values)
            xs.append(limit + offset)
            means.append(mean)
            cis.append(ci)
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


def _draw_pooled(ax: Any, by_evaluator: dict[str, Scores], k: float | None, title: str) -> None:
    methods = [m for m in METHOD_ORDER if all(m in s for s in by_evaluator.values())]
    width = 0.38
    for position, method in enumerate(methods):
        for shift, (name, alpha) in zip((-width / 2, width / 2), (("nano", 0.35), ("mini", 1.0)), strict=True):
            values = _pooled_gap(by_evaluator[name], method) if k is None else _pooled_ck(by_evaluator[name], method, k)
            mean, ci = _mean_ci95(values)
            ax.bar(position + shift, mean, width, yerr=ci, capsize=3, color=METHOD_COLORS[method], alpha=alpha)
            ax.text(position + shift, mean + ci + 0.04, f"{mean:.2f}", ha="center", fontsize=8)
    ax.set_xticks(range(len(methods)))
    ax.set_xticklabels([DISPLAY_NAMES[m] for m in methods])
    ax.set_title(title)
    ax.grid(axis="y", alpha=0.3)


def _draw_k_sweep(ax: Any, scores: Scores) -> None:
    methods = [m for m in METHOD_ORDER if m in scores]
    for method in methods:
        stats = [_mean_ci95(_pooled_ck(scores, method, k)) for k in K_SWEEP]
        ax.errorbar(
            K_SWEEP,
            [mean for mean, _ in stats],
            yerr=[ci for _, ci in stats],
            marker="o",
            linewidth=2,
            capsize=3,
            color=METHOD_COLORS[method],
            label=DISPLAY_NAMES[method],
        )
        ax.annotate(
            f"{stats[-1][0]:.2f}",
            (K_SWEEP[-1], stats[-1][0]),
            xytext=(6, 0),
            textcoords="offset points",
            va="center",
            fontsize=8,
        )
    ax.set_xticks(K_SWEEP)
    ax.set_xlim(-0.05, 1.12)
    ax.set_xlabel("ペナルティ重み k（大きいほど偏りを重く見る）")
    ax.grid(alpha=0.3)


def main() -> None:
    """CLI entrypoint."""
    args = _parse_args()
    experiment_dir = args.experiment_dir.resolve()
    out_dir = (args.out_dir or experiment_dir).resolve()
    by_evaluator = {name: _collect(experiment_dir, subdir) for name, subdir in EVALUATORS}
    by_evaluator = {name: scores for name, scores in by_evaluator.items() if scores}
    if not by_evaluator:
        raise SystemExit(f"SVI の評価結果が見つかりません: {experiment_dir}")
    limits = sorted({limit for s in by_evaluator.values() for per in s.values() for limit in per})
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1) 設定ターン数ごとの C_k（評価器ごとのパネル、縦軸は共通）
    fig, axes = plt.subplots(1, len(by_evaluator), figsize=(5.6 * len(by_evaluator), 4.6), sharey=True)
    axes = [axes] if len(by_evaluator) == 1 else list(axes)
    for ax, (name, scores) in zip(axes, by_evaluator.items(), strict=True):
        _draw_lines(ax, scores, limits, args.k)
        ax.set_title(f"SVI 合意スコア C_k（評価器: {name}）")
    axes[0].set_ylabel(f"合意スコア（高いほど良い、k={args.k}）")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", ncol=len(labels), frameon=False)
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    fig.savefig(out_dir / "svi_by_turns.png", dpi=160)
    plt.close(fig)

    # 2) k を変えたときの C_k（全設定合算）
    fig, axes = plt.subplots(1, len(by_evaluator), figsize=(5.6 * len(by_evaluator), 4.6), sharey=True)
    axes = [axes] if len(by_evaluator) == 1 else list(axes)
    for ax, (name, scores) in zip(axes, by_evaluator.items(), strict=True):
        _draw_k_sweep(ax, scores)
        ax.set_title(f"k を変えたときの合意スコア C_k（評価器: {name}、全設定合算）")
    axes[0].set_ylabel("合意スコア C_k = (A+B)/2 - k|A-B|")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", ncol=len(labels), frameon=False)
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    fig.savefig(out_dir / "svi_k_sweep.png", dpi=160)
    plt.close(fig)

    # 3) 全設定を合算した C_k と |A-B|（薄い棒 nano・濃い棒 mini）
    if len(by_evaluator) == 2:
        fig, axes = plt.subplots(1, 2, figsize=(11, 4.6))
        _draw_pooled(axes[0], by_evaluator, args.k, f"合意スコア C_k（k={args.k}、全設定合算、95% CI）")
        _draw_pooled(axes[1], by_evaluator, None, "AG1 と AG2 の満足度の差 |A-B|（低いほど偏りが小さい）")
        axes[0].set_ylabel("C_k")
        axes[1].set_ylabel("|A-B|")
        legend = [Rectangle((0, 0), 1, 1, color="#555555", alpha=0.35), Rectangle((0, 0), 1, 1, color="#555555")]
        fig.legend(legend, ["nano", "mini"], loc="upper center", ncol=2, frameon=False)
        fig.tight_layout(rect=(0, 0, 1, 0.93))
        fig.savefig(out_dir / "svi_pooled.png", dpi=160)
        plt.close(fig)

    with (out_dir / "svi_by_evaluator.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["evaluator", "method", "max_dialogue_turns", "n", "C_k_mean", "C_k_ci95", "gap_mean"])
        for name, scores in by_evaluator.items():
            for method in METHOD_ORDER:
                for limit in limits:
                    pairs = scores.get(method, {}).get(limit)
                    if pairs:
                        mean, ci = _mean_ci95([_ck(p, args.k) for p in pairs])
                        writer.writerow([name, method, limit, len(pairs), round(mean, 4), round(ci, 4), round(statistics.mean(p[1] for p in pairs), 4)])
    print(f"Saved: {out_dir / 'svi_by_turns.png'}")


if __name__ == "__main__":
    main()
