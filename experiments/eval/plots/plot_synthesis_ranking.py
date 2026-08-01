r"""止揚統合比較実験（5条件）の Constraint Preservation 相対ランキングをグラフ化する.

`eval_synthesis_ranking.py` の出力（<root>/eval_results_ranking.json）を読み、
2つの比較グループについて、横軸=max_dialogue_turns、縦軸=平均順位（1が最良）の
折れ線グラフと、全体平均順位の棒グラフを作る。

Usage:
    python -m experiments.eval.plots.plot_synthesis_ranking \\
      --root logs/synthesis_comparison_full \\
      --out-dir logs/synthesis_comparison_full/plots
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import matplotlib.pyplot as plt

plt.rcParams["font.family"] = ["Hiragino Sans", "sans-serif"]

CONDITIONS = (
    "mad_judge",
    "mad_synthesis",
    "free_debate_synthesis",
    "no_schema_synthesis",
    "schema_synthesis",
)
DISPLAY_NAMES = {
    "mad_judge": "MAD (judge)",
    "mad_synthesis": "MAD (synthesis)",
    "free_debate_synthesis": "Free Debate (synthesis)",
    "no_schema_synthesis": "No Schema (synthesis)",
    "schema_synthesis": "Schema (synthesis)",
}
COLORS = {
    "mad_judge": "#DC2626",
    "mad_synthesis": "#F97316",
    "free_debate_synthesis": "#16A34A",
    "no_schema_synthesis": "#F59E0B",
    "schema_synthesis": "#2563EB",
}
GROUP_INTEGRATION = ["mad_judge", "schema_synthesis"]
GROUP_PROCESS = ["mad_synthesis", "free_debate_synthesis", "no_schema_synthesis", "schema_synthesis"]

TURNS_PATTERN = re.compile(r"^turns(?P<turns>\d+)$")


def _load(eval_json: Path) -> tuple[dict[str, dict[int, float]], dict[str, float]]:
    data = json.loads(eval_json.read_text(encoding="utf-8"))
    by_turns: dict[str, dict[int, float]] = {c: {} for c in CONDITIONS}
    for group, entry in data["summary_by_turns"].items():
        match = TURNS_PATTERN.fullmatch(group)
        if match is None:
            continue
        turns = int(match.group("turns"))
        for condition in CONDITIONS:
            value = entry.get(condition)
            if isinstance(value, (int, float)):
                by_turns[condition][turns] = float(value)
    overall = {
        c: float(v) for c, v in data["overall_mean_rank"].items() if isinstance(v, (int, float))
    }
    return by_turns, overall


def _plot_lines(
    conditions: list[str],
    by_turns: dict[str, dict[int, float]],
    *,
    title: str,
    out_path: Path,
) -> None:
    all_turns = sorted({t for c in conditions for t in by_turns[c]})
    fig, ax = plt.subplots(figsize=(9, 5.5))
    for c in conditions:
        xs = sorted(by_turns[c])
        ys = [by_turns[c][x] for x in xs]
        ax.plot(
            xs, ys, marker="o", markersize=5, linewidth=2.2,
            label=DISPLAY_NAMES[c], color=COLORS[c],
        )
    ax.set_title(title, fontsize=14, pad=12)
    ax.set_xlabel("max_dialogue_turns")
    ax.set_ylabel("Mean rank (1 = best, 5 = worst)")
    if all_turns:
        ax.set_xticks(all_turns)
    ax.invert_yaxis()  # 上に行くほど良い、が直感的に見えるように反転
    ax.grid(axis="y", alpha=0.25)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, loc="best")
    fig.tight_layout()
    fig.savefig(out_path, dpi=180, bbox_inches="tight")
    plt.close(fig)


def _plot_bar(
    conditions: list[str],
    overall: dict[str, float],
    *,
    title: str,
    out_path: Path,
) -> None:
    fig, ax = plt.subplots(figsize=(7.5, 5.2))
    values = [overall[c] for c in conditions]
    colors = [COLORS[c] for c in conditions]
    bars = ax.bar([DISPLAY_NAMES[c] for c in conditions], values, color=colors)
    for bar, value in zip(bars, values, strict=True):
        ax.text(
            bar.get_x() + bar.get_width() / 2, value + 0.03, f"{value:.2f}",
            ha="center", va="bottom", fontsize=10,
        )
    ax.set_title(title, fontsize=14, pad=12)
    ax.set_ylabel("Overall mean rank (1 = best, 5 = worst)")
    ax.invert_yaxis()
    ax.grid(axis="y", alpha=0.25)
    ax.spines[["top", "right"]].set_visible(False)
    plt.setp(ax.get_xticklabels(), rotation=15, ha="right")
    fig.tight_layout()
    fig.savefig(out_path, dpi=180, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    """Constraint Preservation 相対ランキングの比較グラフを出力する."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", required=True, type=Path,
        help="eval_synthesis_ranking.py の --root（eval_results_ranking.jsonの親）。",
    )
    parser.add_argument("--out-dir", required=True, type=Path)
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    eval_json = args.root / "eval_results_ranking.json"
    if not eval_json.exists():
        raise FileNotFoundError(
            f"{eval_json} not found. Run eval_synthesis_ranking.py --root {args.root} first."
        )
    by_turns, overall = _load(eval_json)

    _plot_lines(
        GROUP_INTEGRATION, by_turns,
        title="統合プロセスの重要性検証: Constraint Preservation ランキング\n(MAD judge vs Schema + synthesis)",
        out_path=args.out_dir / "ranking_integration_process.png",
    )
    _plot_lines(
        GROUP_PROCESS, by_turns,
        title="議論過程の重要性検証: Constraint Preservation ランキング\n(共通の止揚統合、議論プロトコルを比較)",
        out_path=args.out_dir / "ranking_debate_process.png",
    )
    _plot_bar(
        list(CONDITIONS), overall,
        title="全条件 総合順位（全ターン・全トピック平均）",
        out_path=args.out_dir / "ranking_overall.png",
    )

    print(f"3 ranking plots saved under {args.out_dir}")  # noqa: T201


if __name__ == "__main__":
    main()
