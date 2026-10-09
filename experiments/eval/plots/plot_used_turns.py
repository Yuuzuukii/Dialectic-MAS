"""設定ターン数（max_dialogue_turns）ごとの、使用したターン数を、手法別に折れ線で描く.

使用ターン数は、ログの ``dialogue_history`` の件数（main / defeat / counter の発話数。弾かれた手も含む）。
左: 使用ターン数の平均（点線は、設定どおりに使い切った場合）。右: 設定ターン数を使い切った割合。

Usage:
    python -m experiments.eval.plots.plot_used_turns \
      --source logs/experiment_20261009_103401:schema,no_schema \
      --source logs/final:free_debate,mad,mad_synthesis \
      --out-dir logs/experiment_20261009_103401/eval_result/used_turns
"""

# ruff: noqa: T201

from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt

plt.rcParams["font.family"] = ["Hiragino Sans", "sans-serif"]

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
_TURNS_DIR = re.compile(r"turns(\d+)$")
_FILENAME = re.compile(r"^(?:\d+_)?(?P<method>.+)_\d{8}_\d{6}_\d+$")


def _parse_source(text: str) -> tuple[Path, set[str]]:
    root, _, methods = text.partition(":")
    return Path(root), {m for m in methods.split(",") if m}


def collect(sources: list[tuple[Path, set[str]]]) -> dict[str, dict[int, list[int]]]:
    """手法 → 設定ターン数 → 各ログの使用ターン数."""
    used: dict[str, dict[int, list[int]]] = defaultdict(lambda: defaultdict(list))
    for root, methods in sources:
        for turns_dir in sorted(root.glob("turns*")):
            match = _TURNS_DIR.search(turns_dir.name)
            if match is None:
                continue
            budget = int(match.group(1))
            for path in sorted((turns_dir / "raw_dialogue").glob("*/*/*.json")):
                name = _FILENAME.match(path.stem)
                if name is None or name.group("method") not in methods:
                    continue
                log = json.loads(path.read_text(encoding="utf-8"))
                used[name.group("method")][budget].append(len(log["dialogue_history"]))
    return used


def _plot(used: dict[str, dict[int, list[int]]], path: Path) -> None:
    budgets = sorted({b for per in used.values() for b in per})
    fig, (left, right) = plt.subplots(1, 2, figsize=(11, 4.6))
    left.plot(
        budgets, budgets, linestyle=":", color="#999", label="設定どおり（y = x）"
    )
    for method in METHOD_ORDER:
        if method not in used:
            continue
        means = [statistics.mean(used[method][b]) for b in budgets]
        full = [
            sum(v >= b for v in used[method][b]) / len(used[method][b]) for b in budgets
        ]
        style = {
            "color": METHOD_COLORS[method],
            "marker": "o",
            "label": DISPLAY_NAMES[method],
        }
        left.plot(budgets, means, **style)
        right.plot(budgets, full, **style)
    left.set_xlabel("設定ターン数 (max_dialogue_turns)")
    left.set_ylabel("使用ターン数の平均")
    left.set_xticks(budgets)
    right.set_xlabel("設定ターン数 (max_dialogue_turns)")
    right.set_ylabel("設定ターン数を使い切った割合")
    right.set_xticks(budgets)
    right.set_ylim(0.5, 1.03)
    for ax in (left, right):
        ax.grid(axis="y", alpha=0.3)
        ax.spines[["top", "right"]].set_visible(False)
    left.legend(frameon=False)
    fig.suptitle("設定ターン数ごとの使用ターン数")
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)


def _write_csv(used: dict[str, dict[int, list[int]]], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "method",
                "budget",
                "n_logs",
                "mean_used",
                "min_used",
                "max_used",
                "share_full",
            ]
        )
        for method in METHOD_ORDER:
            for budget in sorted(used.get(method, {})):
                v = used[method][budget]
                writer.writerow(
                    [
                        method,
                        budget,
                        len(v),
                        f"{statistics.mean(v):.2f}",
                        min(v),
                        max(v),
                        f"{sum(x >= budget for x in v) / len(v):.3f}",
                    ]
                )


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--source", action="append", type=_parse_source, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    used = collect(args.source)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    _plot(used, args.out_dir / "used_turns_lines.png")
    _write_csv(used, args.out_dir / "used_turns_summary.csv")
    print(f"saved to {args.out_dir}")


if __name__ == "__main__":
    main()
