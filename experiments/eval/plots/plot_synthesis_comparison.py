r"""止揚統合比較実験（5条件）の Constraint Preservation と対話ターン消費数を比較する.

2つの比較グループの折れ線グラフ（横軸: max_dialogue_turns）を作る:
  - 統合プロセスの重要性検証: mad_judge（勝者を決めるMAD） vs schema_synthesis（止揚統合）
  - 議論過程の重要性検証: mad_synthesis / free_debate_synthesis / no_schema_synthesis / schema_synthesis
    （いずれも共通の止揚統合を使う）

各条件ディレクトリは run_synthesis_comparison.py が出力した
  <root>/<condition>/turnsNN_attempts01/<category>/<topic>/{method}_*.json
という turns-first のsweep構造を前提とする。Constraint Preservation は
eval_sweep_rubrics.py の出力（<root>/<condition>/eval_results_rubrics.json）から読む。
対話ターン消費数（回答生成を除く、議論フェーズの発話数）はログの dialogue_history の
長さを直接集計する（LLM評価は不要）。

Usage:
    python -m experiments.eval.plots.plot_synthesis_comparison \\
      --root logs/synthesis_comparison_full \\
      --out-dir logs/synthesis_comparison_full/plots
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


def _load_overall_with_ci(eval_json: Path) -> tuple[float, float]:
    """eval_sweep_rubrics.py の per_run から、全セル込みの平均と95%CIの半幅を計算する."""
    data = json.loads(eval_json.read_text(encoding="utf-8"))
    vals = [
        float(r["constraint_preservation"])
        for r in data["per_run"]
        if isinstance(r.get("constraint_preservation"), (int, float))
    ]
    n = len(vals)
    mean = sum(vals) / n
    variance = sum((v - mean) ** 2 for v in vals) / (n - 1)
    sem = (variance**0.5) / (n**0.5)
    return mean, 1.96 * sem


def _load_preservation(eval_json: Path) -> dict[int, float]:
    """eval_sweep_rubrics.py の出力から turns別の constraint_preservation 平均を読む."""
    data = json.loads(eval_json.read_text(encoding="utf-8"))
    summary = data["summary_by_turns"]
    out: dict[int, float] = {}
    for group, scores in summary.items():
        match = GROUP_PATTERN.fullmatch(group)
        if match is None:
            continue
        turns = int(match.group("turns"))
        value = scores.get("constraint_preservation")
        if isinstance(value, (int, float)):
            out[turns] = float(value)
    return out


def _load_preservation_ci(eval_json: Path) -> dict[int, float]:
    """eval_sweep_rubrics.py の per_run から turns別の95%CI半幅（トピック間ばらつき）を計算する.

    各turnsの値は複数トピックの平均なので、その平均のばらつき（標準誤差）を
    95%CIとして返す。n<=1のturnsは帯を描けないので0を返す。
    """
    data = json.loads(eval_json.read_text(encoding="utf-8"))
    by_turns: dict[int, list[float]] = {}
    for r in data.get("per_run", []):
        turns = r.get("turns")
        value = r.get("constraint_preservation")
        if not isinstance(turns, int) or not isinstance(value, (int, float)):
            continue
        by_turns.setdefault(turns, []).append(float(value))
    out: dict[int, float] = {}
    for turns, vals in by_turns.items():
        n = len(vals)
        if n <= 1:
            out[turns] = 0.0
            continue
        mean = sum(vals) / n
        variance = sum((v - mean) ** 2 for v in vals) / (n - 1)
        sem = (variance**0.5) / (n**0.5)
        out[turns] = 1.96 * sem
    return out


def _topic_scores_by_turns(eval_json: Path) -> dict[int, dict[str, float]]:
    """eval_sweep_rubrics.py の per_run から turns別・トピック別の constraint_preservation を読む.

    log_file のパス（turnsNN_attempts01/<category>/<topic>/...）からトピック名を取り出し、
    条件間でトピックをペアリングできるようにする。
    """
    data = json.loads(eval_json.read_text(encoding="utf-8"))
    out: dict[int, dict[str, float]] = {}
    for r in data.get("per_run", []):
        turns = r.get("turns")
        value = r.get("constraint_preservation")
        log_file = r.get("log_file", "")
        parts = log_file.split("/")
        if not isinstance(turns, int) or not isinstance(value, (int, float)) or len(parts) < 3:
            continue
        topic = parts[2]
        out.setdefault(turns, {})[topic] = float(value)
    return out


def _load_paired_diff(
    eval_json_a: Path, eval_json_b: Path
) -> tuple[dict[int, float], dict[int, float], dict[int, int]]:
    """turns別に、同一トピックでペアリングした (b - a) の平均・95%CI半幅・ペア数を返す.

    条件ごとに独立して平均・CIを取るより、同じトピックでの差分を先に取ってから
    平均する方が、トピック固有の難易度差（そのトピックはどの手法でもスコアが
    低い/高い、等）が相殺されるため、統計的に筋が良い（対応のある差の検定と同じ考え方）。
    """
    scores_a = _topic_scores_by_turns(eval_json_a)
    scores_b = _topic_scores_by_turns(eval_json_b)

    means: dict[int, float] = {}
    cis: dict[int, float] = {}
    ns: dict[int, int] = {}
    for turns in sorted(set(scores_a) & set(scores_b)):
        topics = sorted(set(scores_a[turns]) & set(scores_b[turns]))
        diffs = [scores_b[turns][t] - scores_a[turns][t] for t in topics]
        n = len(diffs)
        if n == 0:
            continue
        mean = sum(diffs) / n
        if n > 1:
            variance = sum((d - mean) ** 2 for d in diffs) / (n - 1)
            sem = (variance**0.5) / (n**0.5)
            ci = 1.96 * sem
        else:
            ci = 0.0
        means[turns] = mean
        cis[turns] = ci
        ns[turns] = n
    return means, cis, ns


def _turn_counts_raw(condition_dir: Path) -> dict[int, list[int]]:
    """条件ディレクトリ配下の生ログから turns別の実発話数（dialogue_historyの長さ）の生リストを集計する.

    LLM評価は使わず、ログの dialogue_history をそのまま数える（統合・最終回答は含まれない、
    src/agent/nodes.py の _dialogue_turn_budget_exceeded と同じ対象）。
    """
    per_turns: dict[int, list[int]] = {}
    for json_path in sorted(condition_dir.rglob("*.json")):
        rel = json_path.relative_to(condition_dir)
        if len(rel.parts) < 2:
            continue
        match = GROUP_PATTERN.fullmatch(rel.parts[0])
        if match is None:
            continue
        turns_budget = int(match.group("turns"))
        log = json.loads(json_path.read_text(encoding="utf-8"))
        used = len(log.get("dialogue_history") or [])
        per_turns.setdefault(turns_budget, []).append(used)
    return per_turns


def _turn_counts_from_logs(condition_dir: Path) -> dict[int, float]:
    """turns別の実発話数の平均を返す."""
    per_turns = _turn_counts_raw(condition_dir)
    return {t: sum(v) / len(v) for t, v in per_turns.items() if v}


def _turn_counts_ci_from_logs(condition_dir: Path) -> dict[int, float]:
    """turns別の実発話数の95%CI半幅（トピック間ばらつき）を返す."""
    per_turns = _turn_counts_raw(condition_dir)
    out: dict[int, float] = {}
    for t, vals in per_turns.items():
        n = len(vals)
        if n <= 1:
            out[t] = 0.0
            continue
        mean = sum(vals) / n
        variance = sum((v - mean) ** 2 for v in vals) / (n - 1)
        sem = (variance**0.5) / (n**0.5)
        out[t] = 1.96 * sem
    return out


def _write_csv(
    conditions: list[str],
    preservation: dict[str, dict[int, float]],
    turn_counts: dict[str, dict[int, float]],
    out_path: Path,
) -> None:
    fieldnames = ["condition", "max_dialogue_turns", "constraint_preservation", "turns_used"]
    with out_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for c in conditions:
            turns_set = sorted(set(preservation[c]) | set(turn_counts[c]))
            for t in turns_set:
                writer.writerow(
                    {
                        "condition": c,
                        "max_dialogue_turns": t,
                        "constraint_preservation": preservation[c].get(t),
                        "turns_used": turn_counts[c].get(t),
                    }
                )


def _plot_line(
    conditions: list[str],
    series: dict[str, dict[int, float]],
    *,
    title: str,
    ylabel: str,
    out_path: Path,
    reference_diagonal: bool = False,
    ci: dict[str, dict[int, float]] | None = None,
) -> None:
    all_turns = sorted({t for c in conditions for t in series[c]})
    fig, ax = plt.subplots(figsize=(9, 5.5))
    for c in conditions:
        xs = sorted(series[c])
        ys = [series[c][x] for x in xs]
        ax.plot(
            xs,
            ys,
            marker="o",
            markersize=5,
            linewidth=2.2,
            label=DISPLAY_NAMES[c],
            color=COLORS[c],
        )
        if ci is not None:
            errs = [ci[c].get(x, 0.0) for x in xs]
            lower = [y - e for y, e in zip(ys, errs, strict=True)]
            upper = [y + e for y, e in zip(ys, errs, strict=True)]
            ax.fill_between(xs, lower, upper, color=COLORS[c], alpha=0.15, linewidth=0)
    if reference_diagonal and all_turns:
        ax.plot(
            all_turns,
            all_turns,
            linestyle="--",
            linewidth=1.2,
            color="gray",
            label="budget (y = x)",
        )
    ax.set_title(title, fontsize=14, pad=12)
    ax.set_xlabel("max_dialogue_turns")
    ax.set_ylabel(ylabel)
    if all_turns:
        ax.set_xticks(all_turns)
    ax.grid(axis="y", alpha=0.25)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, loc="best")
    fig.tight_layout()
    fig.savefig(out_path, dpi=180, bbox_inches="tight")
    plt.close(fig)


def _plot_paired_diff(
    means: dict[int, float],
    ci: dict[int, float],
    ns: dict[int, int],
    *,
    title: str,
    ylabel: str,
    out_path: Path,
    color: str = "#7C3AED",
) -> None:
    """turns別のペアリング差分（平均 ± 95%CI）を、0を基準線にして描く."""
    xs = sorted(means)
    ys = [means[x] for x in xs]
    errs = [ci[x] for x in xs]
    lower = [y - e for y, e in zip(ys, errs, strict=True)]
    upper = [y + e for y, e in zip(ys, errs, strict=True)]

    fig, ax = plt.subplots(figsize=(9, 5.5))
    ax.axhline(0, color="#6B7280", linestyle="--", linewidth=1.2)
    ax.plot(xs, ys, marker="o", markersize=5, linewidth=2.2, color=color)
    ax.fill_between(xs, lower, upper, color=color, alpha=0.18, linewidth=0)
    for x, y, n in zip(xs, ys, [ns[x] for x in xs], strict=True):
        ax.annotate(
            f"n={n}", (x, y), textcoords="offset points", xytext=(0, 10),
            ha="center", fontsize=8, color="#6B7280",
        )
    ax.set_title(title, fontsize=14, pad=12)
    ax.set_xlabel("max_dialogue_turns")
    ax.set_ylabel(ylabel)
    ax.set_xticks(xs)
    ax.grid(axis="y", alpha=0.25)
    ax.spines[["top", "right"]].set_visible(False)
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
        [DISPLAY_NAMES[c] for c in conditions],
        means,
        yerr=errs,
        capsize=6,
        color=colors,
        ecolor="#374151",
    )
    for bar, mean in zip(bars, means, strict=True):
        ax.text(
            bar.get_x() + bar.get_width() / 2, mean + 0.05, f"{mean:.2f}",
            ha="center", va="bottom", fontsize=10,
        )
    ax.set_title(title, fontsize=14, pad=12)
    ax.set_ylabel("Mean constraint_preservation score (1-10), 95% CI")
    ax.set_ylim(0, 10)
    ax.grid(axis="y", alpha=0.25)
    ax.spines[["top", "right"]].set_visible(False)
    plt.setp(ax.get_xticklabels(), rotation=15, ha="right")
    fig.tight_layout()
    fig.savefig(out_path, dpi=180, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    """Constraint Preservation と対話ターン消費数の比較グラフを出力する."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        required=True,
        type=Path,
        help="run_synthesis_comparison.py の --output-root（5条件ディレクトリの親）。",
    )
    parser.add_argument("--out-dir", required=True, type=Path)
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)

    preservation: dict[str, dict[int, float]] = {}
    preservation_ci: dict[str, dict[int, float]] = {}
    turn_counts: dict[str, dict[int, float]] = {}
    turn_counts_ci: dict[str, dict[int, float]] = {}
    overall: dict[str, tuple[float, float]] = {}
    for condition in CONDITIONS:
        condition_dir = args.root / condition
        eval_json = condition_dir / "eval_results_rubrics.json"
        if not eval_json.exists():
            raise FileNotFoundError(
                f"{eval_json} not found. Run eval_sweep_rubrics.py --sweep {condition_dir} first."
            )
        preservation[condition] = _load_preservation(eval_json)
        preservation_ci[condition] = _load_preservation_ci(eval_json)
        turn_counts[condition] = _turn_counts_from_logs(condition_dir)
        turn_counts_ci[condition] = _turn_counts_ci_from_logs(condition_dir)
        overall[condition] = _load_overall_with_ci(eval_json)

    _write_csv(list(CONDITIONS), preservation, turn_counts, args.out_dir / "synthesis_comparison.csv")

    _plot_line(
        GROUP_INTEGRATION,
        preservation,
        title="統合プロセスの重要性検証: Constraint Preservation\n(MAD judge vs Schema + synthesis)",
        ylabel="Mean constraint_preservation score (1-10)",
        out_path=args.out_dir / "integration_process_preservation.png",
        ci=preservation_ci,
    )
    _plot_line(
        GROUP_INTEGRATION,
        turn_counts,
        title="統合プロセスの重要性検証: 対話フェーズの発話数\n(MAD judge vs Schema + synthesis)",
        ylabel="Mean dialogue turns used",
        out_path=args.out_dir / "integration_process_turns_used.png",
        reference_diagonal=True,
        ci=turn_counts_ci,
    )
    _plot_line(
        GROUP_PROCESS,
        preservation,
        title="議論過程の重要性検証: Constraint Preservation\n(共通の止揚統合、議論プロトコルを比較)",
        ylabel="Mean constraint_preservation score (1-10)",
        out_path=args.out_dir / "debate_process_preservation.png",
        ci=preservation_ci,
    )
    _plot_line(
        GROUP_PROCESS,
        turn_counts,
        title="議論過程の重要性検証: 対話フェーズの発話数\n(共通の止揚統合、議論プロトコルを比較)",
        ylabel="Mean dialogue turns used",
        out_path=args.out_dir / "debate_process_turns_used.png",
        reference_diagonal=True,
        ci=turn_counts_ci,
    )
    _plot_overall_bar(
        list(CONDITIONS),
        overall,
        title="全条件 総合 Constraint Preservation（全ターン・全トピック平均 ± 95%CI）",
        out_path=args.out_dir / "overall_preservation_with_ci.png",
    )

    diff_means, diff_ci, diff_ns = _load_paired_diff(
        args.root / "mad_judge" / "eval_results_rubrics.json",
        args.root / "schema_synthesis" / "eval_results_rubrics.json",
    )
    _plot_paired_diff(
        diff_means,
        diff_ci,
        diff_ns,
        title=(
            "統合プロセスの重要性検証: Constraint Preservationの差分\n"
            "(Schema + synthesis − MAD judge、同一トピックでペアリング、平均 ± 95%CI)"
        ),
        ylabel="Δ constraint_preservation (Schema − MAD)",
        out_path=args.out_dir / "integration_process_preservation_diff.png",
    )

    n_plots = 6
    for other in GROUP_PROCESS:
        if other == "schema_synthesis":
            continue
        diff_means, diff_ci, diff_ns = _load_paired_diff(
            args.root / other / "eval_results_rubrics.json",
            args.root / "schema_synthesis" / "eval_results_rubrics.json",
        )
        _plot_paired_diff(
            diff_means,
            diff_ci,
            diff_ns,
            title=(
                "議論過程の重要性検証: Constraint Preservationの差分\n"
                f"(Schema + synthesis − {DISPLAY_NAMES[other]}、同一トピックでペアリング、平均 ± 95%CI)"
            ),
            ylabel=f"Δ constraint_preservation (Schema − {DISPLAY_NAMES[other]})",
            out_path=args.out_dir / f"debate_process_preservation_diff_vs_{other}.png",
            color=COLORS[other],
        )
        n_plots += 1

    print(f"CSV + {n_plots} plots saved under {args.out_dir}")  # noqa: T201


if __name__ == "__main__":
    main()
