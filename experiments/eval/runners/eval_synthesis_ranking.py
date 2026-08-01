r"""止揚統合比較実験（5条件）の最終回答を、トピック x ターン数ごとに相対ランキングする.

絶対スコア（1〜10）の holistic 評価はスケールのブレに晒され、n=5トピックでは
ターンごとの折れ線が大きく上下してしまう。同じ (topic, max_dialogue_turns) の
5条件の最終回答を1回のプロンプトにまとめて相対順位をつけさせれば、評価者内の
採点基準は1回の判断で揃うため、より頑健な比較になりうる
（experiments/eval/scoring/evaluation_ranking.py の
`rank_final_answers_by_constraint_preservation` を使用）。

対象ディレクトリ構造（run_synthesis_comparison.py の出力）:
  <root>/<condition>/turnsNN_attempts01/<category>/<topic>/{method}_*.json

Usage:
    python -m experiments.eval.runners.eval_synthesis_ranking \\
      --root logs/synthesis_comparison_full \\
      --workers 11
"""

# print による結果出力と、sys.path 追加後の import はこの評価スクリプトでは意図的。
# ruff: noqa: T201, E402, I001

from __future__ import annotations

import argparse
import json
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv(ROOT / ".env")

from experiments.eval.runners.run_eval import resolve_evaluator_model
from experiments.eval.scoring.evaluation_ranking import (
    rank_final_answers_by_constraint_preservation,
)

CONDITIONS = (
    "mad_judge",
    "mad_synthesis",
    "free_debate_synthesis",
    "no_schema_synthesis",
    "schema_synthesis",
)
GROUP_PATTERN = re.compile(r"^turns(?P<turns>\d+)_attempts\d+$")


class _EvaluatorModel:
    def __init__(self, model_name: str) -> None:
        self.model = model_name
        self._client = ChatOpenAI(model=model_name)

    def invoke(self, prompt: str) -> str:
        response = self._client.invoke(prompt)
        content = response.content
        return content if isinstance(content, str) else "\n".join(str(p) for p in content)


def _discover_cells(root: Path, reference_condition: str) -> list[tuple[int, str, str]]:
    """reference_condition配下を歩いて (turns, category, topic) の一覧を作る."""
    cells: list[tuple[int, str, str]] = []
    ref_dir = root / reference_condition
    for json_path in sorted(ref_dir.rglob("*.json")):
        rel = json_path.relative_to(ref_dir)
        if len(rel.parts) < 4:
            continue
        match = GROUP_PATTERN.fullmatch(rel.parts[0])
        if match is None:
            continue
        turns = int(match.group("turns"))
        category, topic = rel.parts[1], rel.parts[2]
        cells.append((turns, category, topic))
    return cells


def _find_log(root: Path, condition: str, turns: int, category: str, topic: str) -> Path | None:
    combo_dir = root / condition / f"turns{turns:02d}_attempts01" / category / topic
    if not combo_dir.is_dir():
        return None
    matches = sorted(combo_dir.glob("*.json"))
    return matches[0] if matches else None


def _rank_cell(
    root: Path,
    turns: int,
    category: str,
    topic: str,
    model_name: str,
) -> dict[str, Any] | None:
    logs_by_condition: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    for condition in CONDITIONS:
        log_path = _find_log(root, condition, turns, category, topic)
        if log_path is None:
            missing.append(condition)
            continue
        logs_by_condition[condition] = json.loads(log_path.read_text(encoding="utf-8"))
    if missing:
        print(f"[skip] turns={turns} {category}/{topic}: missing {missing}", file=sys.stderr)
        return None

    evaluator = _EvaluatorModel(model_name)
    result = rank_final_answers_by_constraint_preservation(logs_by_condition, evaluator)
    return {
        "turns": turns,
        "category": category,
        "topic": topic,
        "rank": result["key_rank"],
    }


def _run_group(
    turns: int,
    cells: list[tuple[int, str, str]],
    root: Path,
    model_name: str,
    progress_lock: threading.Lock,
    counter: list[int],
) -> list[dict[str, Any]]:
    results = []
    for turns_val, category, topic in cells:
        result = _rank_cell(root, turns_val, category, topic, model_name)
        with progress_lock:
            counter[0] += 1
            if result is not None:
                ranks_str = ", ".join(f"{c}={r}" for c, r in result["rank"].items())
                print(
                    f"[{counter[0]:03d}/{counter[1]}] turns={turns_val} {category}/{topic}: {ranks_str}",
                    flush=True,
                )
        if result is not None:
            results.append(result)
    return results


def _aggregate(all_results: list[dict[str, Any]]) -> dict[str, Any]:
    """turns別・条件別の平均順位と、全体の平均順位を計算する（1が最良）."""
    by_turns: dict[int, dict[str, list[int]]] = {}
    overall: dict[str, list[int]] = {c: [] for c in CONDITIONS}
    for r in all_results:
        turns = r["turns"]
        by_turns.setdefault(turns, {c: [] for c in CONDITIONS})
        for condition, rank in r["rank"].items():
            if rank is None:
                continue
            by_turns[turns][condition].append(rank)
            overall[condition].append(rank)

    summary_by_turns: dict[str, dict[str, Any]] = {}
    for turns in sorted(by_turns):
        entry: dict[str, Any] = {}
        for condition in CONDITIONS:
            ranks = by_turns[turns][condition]
            entry[condition] = round(sum(ranks) / len(ranks), 2) if ranks else None
        summary_by_turns[f"turns{turns:02d}"] = entry

    overall_summary = {
        c: round(sum(v) / len(v), 2) if v else None for c, v in overall.items()
    }
    return {"summary_by_turns": summary_by_turns, "overall_mean_rank": overall_summary}


def _print_table(summary: dict[str, Any]) -> None:
    print()
    print("=" * 100)
    print("CONSTRAINT PRESERVATION — RANKING SUMMARY (1 = best, 5 = worst)")
    print("=" * 100)
    header = f"{'turns':<10}" + "".join(f"{c:<24}" for c in CONDITIONS)
    print(header)
    print("-" * len(header))
    for group, entry in summary["summary_by_turns"].items():
        row = f"{group:<10}" + "".join(f"{str(entry.get(c)):<24}" for c in CONDITIONS)
        print(row)
    print("-" * len(header))
    overall = summary["overall_mean_rank"]
    row = f"{'OVERALL':<10}" + "".join(f"{str(overall.get(c)):<24}" for c in CONDITIONS)
    print(row)
    print()


def main() -> None:
    """止揚統合比較実験の最終回答をトピック x ターン数ごとに相対ランキングする."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        required=True,
        type=Path,
        help="run_synthesis_comparison.py の --output-root（5条件ディレクトリの親）。",
    )
    parser.add_argument("--model", default=None, help="評価器モデル名。")
    parser.add_argument("--out", default=None, type=Path, help="結果JSONの保存先。")
    parser.add_argument(
        "--workers", type=int, default=1, help="turns値単位の並列ワーカー数。"
    )
    args = parser.parse_args()

    root = args.root if args.root.is_absolute() else ROOT / args.root
    if not root.exists():
        print(f"Root not found: {root}", file=sys.stderr)
        sys.exit(1)

    model_name = resolve_evaluator_model(args.model)
    cells = _discover_cells(root, reference_condition="mad_judge")
    if not cells:
        print(f"No cells found under {root}/mad_judge", file=sys.stderr)
        sys.exit(1)

    by_turns: dict[int, list[tuple[int, str, str]]] = {}
    for cell in cells:
        by_turns.setdefault(cell[0], []).append(cell)

    print(f"Ranking {len(cells)} cells x {len(CONDITIONS)} conditions with {model_name} ...")
    print(f"Root: {root}")
    print(f"turns groups: {sorted(by_turns)}  workers={args.workers}")
    print()

    all_results: list[dict[str, Any]] = []
    progress_lock = threading.Lock()
    counter = [0, len(cells)]

    workers = max(1, min(args.workers, len(by_turns)))
    if workers == 1:
        for turns in sorted(by_turns):
            all_results.extend(
                _run_group(turns, by_turns[turns], root, model_name, progress_lock, counter)
            )
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(
                    _run_group, turns, group_cells, root, model_name, progress_lock, counter
                ): turns
                for turns, group_cells in by_turns.items()
            }
            for future in as_completed(futures):
                all_results.extend(future.result())

    summary = _aggregate(all_results)
    _print_table(summary)

    output = {"summary_by_turns": summary["summary_by_turns"], "overall_mean_rank": summary["overall_mean_rank"], "per_cell": all_results}
    out_path = args.out or (root / "eval_results_ranking.json")
    if not out_path.is_absolute():
        out_path = ROOT / out_path
    out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Results saved to {out_path}")


if __name__ == "__main__":
    main()
