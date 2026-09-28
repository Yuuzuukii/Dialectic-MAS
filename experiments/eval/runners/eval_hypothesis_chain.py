"""schema仮説を3段階に分解して、同じログ集合に対して一貫して検証する.

仮説「rebuttal/undercutを明示的に行う→論点が多く出る→対立軸が明確になり合意
しやすい」を対象とする。

1. attack_moves: 議論中の各ターンが rebut/undercut/concede/new のどれかを集計
   （schema/no_schemaは構造フィールドから機械的に、free_debate/madはLLM分類）。
   仮説の出発点（"schemaは反論を明示的に行うか"）を直接検証する。
2. transcript coverage: atomic化したstance項目が、最終回答ではなく議論全体の
   どこかで一度でも提起されたか（"論点が尽きるまで多く出るか"）。
3. objection (with transcript): 議論全体を踏まえた上で、AG1/AG2本人が最終回答に
   なお有効な文句を言えるか（"対立軸が明確になり合意しやすい結論になるか"）。

3つとも同じログ集合（デフォルトは6 topics x 4 methods x 1 trial = 24 logs）に
対して実行し、同一の土台で仮説の連鎖のどこが崩れているかを見られるようにする。

Usage:
    python -m experiments.eval.runners.eval_hypothesis_chain
    python -m experiments.eval.runners.eval_hypothesis_chain --trials 5 --workers 16
"""

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
from experiments.eval.scoring.attack_moves import evaluate_attack_moves
from experiments.eval.scoring.evaluation_coverage_transcript import (
    evaluate_stance_coverage_transcript,
)
from experiments.eval.scoring.evaluation_objection import evaluate_final_answer_objections

LOGS_DIR = ROOT / "logs" / "final_gpt54nano_turns10"
OUT_PATH = LOGS_DIR / "hypothesis_chain.json"
OUT_CSV_PATH = ROOT / "docs" / "results" / "hypothesis_chain.csv"

_FILENAME_RE = re.compile(r"^\d+_(?P<method>.+)_\d{8}_\d{6}_\d+$")


class _JudgeModel:
    def __init__(self, model_name: str) -> None:
        self.model = model_name
        self._client = ChatOpenAI(model=model_name)

    def invoke(self, prompt: str) -> str:
        response = self._client.invoke(prompt)
        content = response.content
        return content if isinstance(content, str) else "\n".join(str(p) for p in content)


def _collect_logs(trials_per_method: int) -> list[Path]:
    all_paths = sorted(LOGS_DIR.glob("*/*/*.json"))
    by_group: dict[tuple[str, str], list[Path]] = {}
    for p in all_paths:
        m = _FILENAME_RE.match(p.stem)
        method = m.group("method") if m else p.stem
        by_group.setdefault((p.parent.name, method), []).append(p)
    selected: list[Path] = []
    for group_paths in by_group.values():
        selected.extend(sorted(group_paths)[:trials_per_method])
    return sorted(selected)


def _evaluate_one(log_path: Path, model_name: str) -> dict[str, Any]:
    log = json.loads(log_path.read_text(encoding="utf-8"))
    judge = _JudgeModel(model_name)

    moves = evaluate_attack_moves(log, judge)
    transcript_cov = evaluate_stance_coverage_transcript(log, judge)
    objection = evaluate_final_answer_objections(log, judge)

    return {
        "file": log_path.name,
        "topic": log_path.parent.name,
        "category": log_path.parent.parent.name,
        "method": log.get("method") or log.get("mode"),
        # 1. attack moves
        "moves_rebut": moves.get("rebut"),
        "moves_undercut": moves.get("undercut"),
        "moves_concede": moves.get("concede"),
        "moves_new": moves.get("new"),
        "moves_total": moves.get("total"),
        # 2. transcript-level atomic coverage
        "transcript_covered": transcript_cov.get("covered"),
        "transcript_total": transcript_cov.get("total"),
        "transcript_ratio": transcript_cov.get("ratio"),
        # 3. objection (with full transcript context)
        "agent1_has_objection": objection["agent1"]["has_objection"],
        "agent1_reason": objection["agent1"]["reason"],
        "agent2_has_objection": objection["agent2"]["has_objection"],
        "agent2_reason": objection["agent2"]["reason"],
        "any_objection": objection["any_objection"],
    }


def _mean(values: list[Any]) -> float | None:
    nums = [v for v in values if isinstance(v, (int, float))]
    return round(sum(nums) / len(nums), 4) if nums else None


def _aggregate(results: list[dict[str, Any]]) -> dict[str, Any]:
    by_method: dict[str, list[dict[str, Any]]] = {}
    for r in results:
        by_method.setdefault(r["method"], []).append(r)

    summary: dict[str, Any] = {}
    for method, rows in sorted(by_method.items()):
        attack_total = [
            (r["moves_rebut"] or 0) + (r["moves_undercut"] or 0) for r in rows
        ]
        summary[method] = {
            "n": len(rows),
            # 1
            "rebut_mean": _mean([r["moves_rebut"] for r in rows]),
            "undercut_mean": _mean([r["moves_undercut"] for r in rows]),
            "attack_moves_mean": _mean(attack_total),
            "turns_mean": _mean([r["moves_total"] for r in rows]),
            # 2
            "transcript_coverage_mean": _mean([r["transcript_ratio"] for r in rows]),
            "transcript_items_mean": _mean([r["transcript_total"] for r in rows]),
            # 3
            "agent1_no_objection_rate": round(
                1 - sum(1 for r in rows if r["agent1_has_objection"] is True)
                / max(1, sum(1 for r in rows if isinstance(r["agent1_has_objection"], bool))),
                4,
            ),
            "agent2_no_objection_rate": round(
                1 - sum(1 for r in rows if r["agent2_has_objection"] is True)
                / max(1, sum(1 for r in rows if isinstance(r["agent2_has_objection"], bool))),
                4,
            ),
        }
    return summary


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=None)
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--trials", type=int, default=1)
    args = parser.parse_args()

    model_name = resolve_evaluator_model(args.model)
    log_paths = _collect_logs(args.trials)
    print(f"Evaluating {len(log_paths)} logs across the hypothesis chain ({model_name}, workers={args.workers}) ...")

    results: list[dict[str, Any]] = []
    lock = threading.Lock()
    counter = [0]

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(_evaluate_one, log_path, model_name): log_path
            for log_path in log_paths
        }
        for future in as_completed(futures):
            r = future.result()
            with lock:
                counter[0] += 1
                print(
                    f"[{counter[0]:03d}/{len(log_paths)}] {r['topic']}/{r['file']} "
                    f"rebut={r['moves_rebut']} undercut={r['moves_undercut']} "
                    f"transcript_cov={r['transcript_ratio']} "
                    f"ag1_obj={r['agent1_has_objection']} ag2_obj={r['agent2_has_objection']}",
                    flush=True,
                )
            results.append(r)

    results.sort(key=lambda r: (r["topic"], r["file"]))
    summary = _aggregate(results)

    print()
    print("=" * 100)
    print("HYPOTHESIS CHAIN — SUMMARY BY METHOD")
    print("=" * 100)
    header = (
        f"{'method':<14}{'n':>4}{'rebut':>8}{'undercut':>10}{'turns':>8}"
        f"{'transcript_cov':>16}{'ag1_no_obj':>12}{'ag2_no_obj':>12}"
    )
    print(header)
    for method, agg in summary.items():
        print(
            f"{method:<14}{agg['n']:>4}{agg['rebut_mean']:>8}{agg['undercut_mean']:>10}"
            f"{agg['turns_mean']:>8}{agg['transcript_coverage_mean']:>16}"
            f"{agg['agent1_no_objection_rate']:>12}{agg['agent2_no_objection_rate']:>12}"
        )

    OUT_PATH.write_text(
        json.dumps({"summary_by_method": summary, "detail": results}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nSaved: {OUT_PATH}")

    OUT_CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    header_csv = (
        "topic,category,method,moves_rebut,moves_undercut,moves_concede,moves_new,moves_total,"
        "transcript_covered,transcript_total,transcript_ratio,"
        "agent1_has_objection,agent2_has_objection,any_objection\n"
    )
    lines = [header_csv]
    for r in results:
        lines.append(
            f"{r['topic']},{r['category']},{r['method']},{r['moves_rebut']},{r['moves_undercut']},"
            f"{r['moves_concede']},{r['moves_new']},{r['moves_total']},"
            f"{r['transcript_covered']},{r['transcript_total']},{r['transcript_ratio']},"
            f"{r['agent1_has_objection']},{r['agent2_has_objection']},{r['any_objection']}\n"
        )
    OUT_CSV_PATH.write_text("".join(lines), encoding="utf-8")
    print(f"Saved: {OUT_CSV_PATH}")


if __name__ == "__main__":
    main()
