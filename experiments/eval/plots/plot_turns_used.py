"""設定ターン数と、実際に使われたターン数を手法別の折れ線にする.

横軸は設定ターン数（max_dialogue_turns）、縦軸は実際に使った対話ターン数
（dialogue_history の発話数）。点は手法ごとの平均、誤差棒は 95% CI（ログ単位）、
薄い点は個々のログ。破線 y = x は上限（使い切った場合）で、これを下回るほど、
議論が上限より前に止まったことを示す。

入力は logs/experiment_<日時>/（turns<N>/raw_dialogue/ 配下のログを読む）。

出力（既定は実験フォルダ直下）:
- turns_used.png : 折れ線グラフ
- turns_used.csv : 手法 × 設定ターン数の平均・最小・最大・n

Usage:
    python -m experiments.eval.plots.plot_turns_used logs/experiment_20261001_213109
"""

# ruff: noqa: T201

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import statistics
from collections import defaultdict
from pathlib import Path

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
_TURNS_DIR_RE = re.compile(r"^turns(\d+)$")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("experiment_dir", type=Path, help="logs/experiment_<日時>")
    parser.add_argument("--out-dir", type=Path, default=None, help="既定は実験フォルダ直下。")
    parser.add_argument("--no-ci", action="store_true", help="95%% CI の誤差棒を描かない。")
    return parser.parse_args()


def _mean_ci95(values: list[int]) -> tuple[float, float]:
    if len(values) < 2:
        return (float(values[0]) if values else math.nan), 0.0
    return statistics.mean(values), 1.96 * statistics.stdev(values) / math.sqrt(len(values))


def _collect(experiment_dir: Path) -> dict[str, dict[int, list[int]]]:
    """手法 → 設定ターン数 → ログ単位の使用ターン数."""
    used: dict[str, dict[int, list[int]]] = defaultdict(lambda: defaultdict(list))
    for turns_dir in sorted(experiment_dir.iterdir()):
        match = _TURNS_DIR_RE.match(turns_dir.name)
        if not match or not turns_dir.is_dir():
            continue
        limit = int(match.group(1))
        for path in sorted((turns_dir / "raw_dialogue").glob("*/*/*.json")):
            log = json.loads(path.read_text(encoding="utf-8"))
            method = log.get("method")
            if method in METHOD_ORDER:
                used[method][limit].append(len(log.get("dialogue_history", [])))
    return used


def _plot(used: dict[str, dict[int, list[int]]], path: Path, show_ci: bool) -> None:
    limits = sorted({limit for per in used.values() for limit in per})
    fig, ax = plt.subplots(figsize=(7.5, 5.5))
    top = max(limits)
    ax.plot([0, top + 2], [0, top + 2], color="#bbbbbb", linestyle="--", linewidth=1.2, label="上限（y = x）", zorder=1)

    methods = [m for m in METHOD_ORDER if m in used]
    spread = 0.35  # 同じ値の手法が重ならないよう、横軸を少しずらして描く
    for index, method in enumerate(methods):
        offset = (index - (len(methods) - 1) / 2) * spread
        xs = [limit + offset for limit in limits if limit in used[method]]
        stats = [_mean_ci95(used[method][limit]) for limit in limits if limit in used[method]]
        color = METHOD_COLORS[method]
        for limit in limits:
            values = used[method].get(limit, [])
            ax.scatter([limit + offset] * len(values), values, s=14, color=color, alpha=0.25, zorder=2)
        means = [m for m, _ in stats]
        # 使用ターン数は設定ターン数を超えないので、誤差棒の上側は上限で止める。
        ylimits = [limit for limit in limits if limit in used[method]]
        yerr = [
            [min(c, m) for m, (_, c) in zip(means, stats, strict=True)],
            [max(0.0, min(c, lim - m)) for m, (_, c), lim in zip(means, stats, ylimits, strict=True)],
        ]
        ax.errorbar(
            xs,
            means,
            yerr=yerr if show_ci else None,
            marker="o",
            linewidth=2,
            capsize=3,
            color=color,
            label=DISPLAY_NAMES[method],
            zorder=3,
        )

    ax.set_xticks(limits)
    ax.set_xlabel("設定ターン数（max_dialogue_turns）")
    ax.set_ylabel("実際に使ったターン数")
    ax.set_xlim(min(limits) - 3, top + 3)
    ax.set_ylim(0, top + 3)
    ax.grid(alpha=0.3)
    ax.set_title("設定ターン数と使用ターン数（上限を下回るほど、上限より前に止まった）")
    ax.legend(loc="upper left")
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def main() -> None:
    """CLI entrypoint."""
    args = _parse_args()
    experiment_dir = args.experiment_dir.resolve()
    out_dir = (args.out_dir or experiment_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    used = _collect(experiment_dir)
    if not used:
        raise SystemExit(f"turns<N>/raw_dialogue のログが見つかりません: {experiment_dir}")

    _plot(used, out_dir / "turns_used.png", show_ci=not args.no_ci)
    with (out_dir / "turns_used.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["method", "max_dialogue_turns", "n", "mean_used", "min_used", "max_used", "ci95"])
        for method in METHOD_ORDER:
            for limit in sorted(used.get(method, {})):
                values = used[method][limit]
                mean, ci = _mean_ci95(values)
                writer.writerow([method, limit, len(values), round(mean, 2), min(values), max(values), round(ci, 2)])
                print(f"{method:<12} limit={limit:<3} n={len(values)} mean={mean:.1f} range=[{min(values)}, {max(values)}]")
    print(f"\nSaved: {out_dir / 'turns_used.png'}")


if __name__ == "__main__":
    main()
