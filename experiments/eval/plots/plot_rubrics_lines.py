"""複数方式のルーブリック評価結果を設定別の折れ線グラフにする.

Schema / No Schema は attempts、MAD / Free Debate は turns を
横軸の setting として比較する。

Usage:
    python -m experiments.eval.plots.plot_rubrics_lines \
      --schema path/to/schema_eval.json \
      --no-schema path/to/no_schema_eval.json \
      --mad path/to/mad_eval.json \
      --free-debate path/to/free_debate_eval.json \
      --out-dir logs/eval_comparison
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt

METRICS = (
    "constructiveness",
    "constraint_preservation",
    "quality_average_v2",
)
METHODS = (
    ("Schema", "schema", "attempts"),
    ("No Schema", "no_schema", "attempts"),
    ("MAD", "mad", "turns"),
    ("Free Debate", "free_debate", "turns"),
)
COLORS = {
    "Schema": "#2563EB",
    "No Schema": "#F59E0B",
    "MAD": "#DC2626",
    "Free Debate": "#16A34A",
}
GROUP_PATTERN = re.compile(r"^turns(?P<turns>\d+)_attempts(?P<attempts>\d+)$")


def _load_summary(path: Path, setting_kind: str) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    summary = data["summary_by_turns"]
    rows: list[dict[str, Any]] = []

    for group, scores in summary.items():
        match = GROUP_PATTERN.fullmatch(group)
        if match is None:
            raise ValueError(f"Unexpected group name in {path}: {group}")
        setting = int(match.group(setting_kind))
        row = {
            "setting": setting,
            "group": group,
            "n": int(scores["n"]),
            "n_valid": int(scores["n_valid"]),
        }
        row.update({metric: float(scores[metric]) for metric in METRICS})
        rows.append(row)

    rows.sort(key=lambda row: row["setting"])
    if [row["setting"] for row in rows] != list(range(1, 11)):
        raise ValueError(f"Expected settings 1..10 in {path}")
    if any(row["n"] != 10 or row["n_valid"] != 10 for row in rows):
        raise ValueError(f"Expected 10/10 valid evaluations per setting in {path}")
    return rows


def _write_csv(all_rows: dict[str, list[dict[str, Any]]], out_path: Path) -> None:
    fieldnames = ["method", "setting", "setting_kind", "group", "n", "n_valid", *METRICS]
    with out_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for display_name, _, setting_kind in METHODS:
            for row in all_rows[display_name]:
                writer.writerow(
                    {
                        "method": display_name,
                        "setting_kind": setting_kind,
                        **row,
                    }
                )


def _plot_metric(
    all_rows: dict[str, list[dict[str, Any]]],
    metric: str,
    out_path: Path,
) -> None:
    fig, ax = plt.subplots(figsize=(10.5, 6.2))
    for display_name, _, _ in METHODS:
        rows = all_rows[display_name]
        ax.plot(
            [row["setting"] for row in rows],
            [row[metric] for row in rows],
            color=COLORS[display_name],
            label=display_name,
            linewidth=2.2,
            marker="o",
            markersize=5,
        )

    title = metric.replace("_", " ").title()
    ax.set_title(f"{title} by Setting", fontsize=15, pad=14)
    ax.set_xlabel("Setting (Schema/No Schema: attempts; MAD/Free Debate: turns)")
    ax.set_ylabel("Mean score (1–10)")
    ax.set_xticks(range(1, 11))
    ax.set_ylim(1, 10.25)
    ax.grid(axis="y", alpha=0.25)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(ncol=2, frameon=False, loc="lower center")
    fig.tight_layout()
    fig.savefig(out_path, dpi=180, bbox_inches="tight")
    plt.close(fig)


def _plot_combined(
    all_rows: dict[str, list[dict[str, Any]]],
    out_path: Path,
) -> None:
    metrics = ("constructiveness", "constraint_preservation")
    fig, axes = plt.subplots(1, 2, figsize=(15, 5.8), sharex=True, sharey=True)

    for ax, metric in zip(axes, metrics, strict=True):
        for display_name, _, _ in METHODS:
            rows = all_rows[display_name]
            ax.plot(
                [row["setting"] for row in rows],
                [row[metric] for row in rows],
                color=COLORS[display_name],
                label=display_name,
                linewidth=2.2,
                marker="o",
                markersize=4.5,
            )
        ax.set_title(metric.replace("_", " ").title(), fontsize=14)
        ax.set_xlabel("Setting")
        ax.set_xticks(range(1, 11))
        ax.set_ylim(1, 10.25)
        ax.grid(axis="y", alpha=0.25)
        ax.spines[["top", "right"]].set_visible(False)

    axes[0].set_ylabel("Mean score (1–10)")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, ncol=4, frameon=False, loc="lower center")
    fig.suptitle(
        "Rubric Scores by Setting\n"
        "Schema/No Schema: attempts; MAD/Free Debate: turns",
        fontsize=15,
    )
    fig.tight_layout(rect=(0, 0.09, 1, 0.93))
    fig.savefig(out_path, dpi=180, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    """CLI 引数から4方式の評価結果を読み込み、CSVとグラフを出力する."""
    parser = argparse.ArgumentParser(description=__doc__)
    for _, argument_name, _ in METHODS:
        parser.add_argument(
            f"--{argument_name.replace('_', '-')}",
            required=True,
            type=Path,
        )
    parser.add_argument("--out-dir", required=True, type=Path)
    args = parser.parse_args()

    inputs = {
        "Schema": args.schema,
        "No Schema": args.no_schema,
        "MAD": args.mad,
        "Free Debate": args.free_debate,
    }
    setting_kinds = {display_name: setting_kind for display_name, _, setting_kind in METHODS}
    all_rows = {
        display_name: _load_summary(path, setting_kinds[display_name])
        for display_name, path in inputs.items()
    }

    args.out_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(all_rows, args.out_dir / "rubrics_summary.csv")
    for metric in METRICS:
        _plot_metric(all_rows, metric, args.out_dir / f"{metric}.png")
    _plot_combined(all_rows, args.out_dir / "rubrics_comparison.png")


if __name__ == "__main__":
    main()
