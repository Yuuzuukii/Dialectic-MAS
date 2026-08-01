r"""スタンス項目カバレッジ率（evaluation_coverage.py）を比較グラフにする.

eval_sweep_coverage.py の出力（<root>/<condition>/eval_results_coverage.json）を
読み、plot_synthesis_comparison.py と同じ2グループ（統合プロセスの重要性検証 /
議論過程の重要性検証）で、横軸=max_dialogue_turns、縦軸=平均カバレッジ率(0-1)の
折れ線グラフ（95%CI帯付き）と、全条件の総合棒グラフを作る。

Usage:
    python -m experiments.eval.plots.plot_synthesis_coverage \\
      --root logs/synthesis_comparison_original5 \\
      --out-dir logs/synthesis_comparison_original5/plots
"""

from __future__ import annotations

import argparse
import csv
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

GROUP_PATTERN = re.compile(r"^turns(?P<turns>\d+)_attempts(?P<attempts>\d+)$")


def _load_ratio_by_turns(eval_json: Path) -> dict[int, list[float]]:
    """eval_sweep_coverage.py の per_run から turns別の ratio 生リストを読む."""
    data = json.loads(eval_json.read_text(encoding="utf-8"))
    out: dict[int, list[float]] = {}
    for r in data.get("per_run", []):
        turns = r.get("turns")
        ratio = r.get("ratio")
        if isinstance(turns, int) and isinstance(ratio, (int, float)):
            out.setdefault(turns, []).append(float(ratio))
    return out


def _mean_and_ci(by_turns: dict[int, list[float]]) -> tuple[dict[int, float], dict[int, float]]:
    means: dict[int, float] = {}
    cis: dict[int, float] = {}
    for turns, vals in by_turns.items():
        n = len(vals)
        mean = sum(vals) / n
        means[turns] = mean
        if n > 1:
            variance = sum((v - mean) ** 2 for v in vals) / (n - 1)
            sem = (variance**0.5) / (n**0.5)
            cis[turns] = 1.96 * sem
        else:
            cis[turns] = 0.0
    return means, cis


def _overall_mean_and_ci(eval_json: Path) -> tuple[float, float]:
    data = json.loads(eval_json.read_text(encoding="utf-8"))
    vals = [
        float(r["ratio"]) for r in data.get("per_run", []) if isinstance(r.get("ratio"), (int, float))
    ]
    n = len(vals)
    mean = sum(vals) / n
    variance = sum((v - mean) ** 2 for v in vals) / (n - 1)
    sem = (variance**0.5) / (n**0.5)
    return mean, 1.96 * sem


def _write_csv(conditions: list[str], means: dict[str, dict[int, float]], out_path: Path) -> None:
    fieldnames = ["condition", "max_dialogue_turns", "coverage_ratio"]
    with out_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for c in conditions:
            for t in sorted(means[c]):
                writer.writerow({"condition": c, "max_dialogue_turns": t, "coverage_ratio": means[c][t]})


def _plot_line(
    conditions: list[str],
    means: dict[str, dict[int, float]],
    ci: dict[str, dict[int, float]],
    *,
    title: str,
    out_path: Path,
) -> None:
    all_turns = sorted({t for c in conditions for t in means[c]})
    fig, ax = plt.subplots(figsize=(9, 5.5))
    for c in conditions:
        xs = sorted(means[c])
        ys = [means[c][x] for x in xs]
        errs = [ci[c].get(x, 0.0) for x in xs]
        lower = [y - e for y, e in zip(ys, errs, strict=True)]
        upper = [y + e for y, e in zip(ys, errs, strict=True)]
        ax.plot(xs, ys, marker="o", markersize=5, linewidth=2.2, label=DISPLAY_NAMES[c], color=COLORS[c])
        ax.fill_between(xs, lower, upper, color=COLORS[c], alpha=0.15, linewidth=0)
    ax.set_title(title, fontsize=14, pad=12)
    ax.set_xlabel("max_dialogue_turns")
    ax.set_ylabel("Mean stance coverage ratio (0-1)")
    ax.set_ylim(0, 1.05)
    if all_turns:
        ax.set_xticks(all_turns)
    ax.grid(axis="y", alpha=0.25)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, loc="best")
    fig.tight_layout()
    fig.savefig(out_path, dpi=180, bbox_inches="tight")
    plt.close(fig)


def _plot_overall_bar(
    conditions: list[str],
    overall: dict[str, tuple[float, float]],
    *,
    title: str,
    out_path: Path,
) -> None:
    fig, ax = plt.subplots(figsize=(7.5, 5.2))
    means = [overall[c][0] for c in conditions]
    errs = [overall[c][1] for c in conditions]
    colors = [COLORS[c] for c in conditions]
    bars = ax.bar(
        [DISPLAY_NAMES[c] for c in conditions], means, yerr=errs, capsize=6, color=colors, ecolor="#374151"
    )
    for bar, mean in zip(bars, means, strict=True):
        ax.text(
            bar.get_x() + bar.get_width() / 2, mean + 0.02, f"{mean:.1%}",
            ha="center", va="bottom", fontsize=10,
        )
    ax.set_title(title, fontsize=14, pad=12)
    ax.set_ylabel("Mean stance coverage ratio (0-1), 95% CI")
    ax.set_ylim(0, 1.05)
    ax.grid(axis="y", alpha=0.25)
    ax.spines[["top", "right"]].set_visible(False)
    plt.setp(ax.get_xticklabels(), rotation=15, ha="right")
    fig.tight_layout()
    fig.savefig(out_path, dpi=180, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    """スタンス項目カバレッジ率の比較グラフを出力する."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)

    means: dict[str, dict[int, float]] = {}
    ci: dict[str, dict[int, float]] = {}
    overall: dict[str, tuple[float, float]] = {}
    for condition in CONDITIONS:
        eval_json = args.root / condition / "eval_results_coverage.json"
        if not eval_json.exists():
            raise FileNotFoundError(
                f"{eval_json} not found. Run eval_sweep_coverage.py --sweep {args.root / condition} first."
            )
        by_turns = _load_ratio_by_turns(eval_json)
        means[condition], ci[condition] = _mean_and_ci(by_turns)
        overall[condition] = _overall_mean_and_ci(eval_json)

    _write_csv(list(CONDITIONS), means, args.out_dir / "synthesis_coverage.csv")

    _plot_line(
        GROUP_INTEGRATION,
        means,
        ci,
        title="統合プロセスの重要性検証: スタンス項目カバレッジ率\n(MAD judge vs Schema + synthesis)",
        out_path=args.out_dir / "integration_process_coverage.png",
    )
    _plot_line(
        GROUP_PROCESS,
        means,
        ci,
        title="議論過程の重要性検証: スタンス項目カバレッジ率\n(共通の止揚統合、議論プロトコルを比較)",
        out_path=args.out_dir / "debate_process_coverage.png",
    )
    _plot_overall_bar(
        list(CONDITIONS),
        overall,
        title="全条件 総合スタンス項目カバレッジ率（全ターン・全トピック平均 ± 95%CI）",
        out_path=args.out_dir / "overall_coverage_with_ci.png",
    )

    print(f"CSV + 3 plots saved under {args.out_dir}")  # noqa: T201


if __name__ == "__main__":
    main()
