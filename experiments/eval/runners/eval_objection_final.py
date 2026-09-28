"""logs/final_gpt54nano_turns10 配下の全120ログを、最終回答への文句の有無で評価する.

議論履歴は見せず、各エージェント本人（AG1/AG2）に自分の stance と final_answer
だけを見せ、一人称で「あなたはこの最終回答に文句があるか」を yes/no 自己申告
させる（第三者の評価者LLMによる代弁ではない。evaluation_objection.evaluate_final_answer_objections）。

Usage:
    python -m experiments.eval.runners.eval_objection_final
    python -m experiments.eval.runners.eval_objection_final --workers 8
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
from experiments.eval.scoring.evaluation_objection import evaluate_final_answer_objections

LOGS_DIR = ROOT / "logs" / "final_gpt54nano_turns10"
OUT_PATH = LOGS_DIR / "objection_comparison.json"
OUT_CSV_PATH = ROOT / "docs" / "results" / "objection_comparison.csv"


class _AgentJudgeModel:
    """AG1/AG2 本人として一人称で自己申告させるための LLM ラッパ（第三者評価者ではない）."""

    def __init__(self, model_name: str) -> None:
        self.model = model_name
        self._client = ChatOpenAI(model=model_name)

    def invoke(self, prompt: str) -> str:
        response = self._client.invoke(prompt)
        content = response.content
        return content if isinstance(content, str) else "\n".join(str(p) for p in content)


_FILENAME_RE = re.compile(r"^\d+_(?P<method>.+)_\d{8}_\d{6}_\d+$")


def _collect_logs(trials_per_method: int) -> list[Path]:
    """各 (topic, method) の組につき、先頭 trials_per_method 件（01, 02, ...）だけを集める.

    ログは 6 topics x 4 methods x 5 trials = 120 件あるが、コスト削減のため
    デフォルトでは各組の1試行目だけ（6 topics x 4 methods = 24 logs）を対象にする。
    """
    all_paths = sorted(LOGS_DIR.glob("*/*/*.json"))
    by_group: dict[tuple[str, str], list[Path]] = {}
    for p in all_paths:
        m = _FILENAME_RE.match(p.stem)
        method = m.group("method") if m else (p.stem)
        by_group.setdefault((p.parent.name, method), []).append(p)
    selected: list[Path] = []
    for group_paths in by_group.values():
        selected.extend(sorted(group_paths)[:trials_per_method])
    return sorted(selected)


def _evaluate_one(log_path: Path, model_name: str) -> dict[str, Any]:
    log = json.loads(log_path.read_text(encoding="utf-8"))
    agent_judge = _AgentJudgeModel(model_name)
    result = evaluate_final_answer_objections(log, agent_judge)
    return {
        "file": log_path.name,
        "topic": log_path.parent.name,
        "category": log_path.parent.parent.name,
        "method": log.get("method") or log.get("mode"),
        "agent1_has_objection": result["agent1"]["has_objection"],
        "agent1_reason": result["agent1"]["reason"],
        "agent2_has_objection": result["agent2"]["has_objection"],
        "agent2_reason": result["agent2"]["reason"],
        "any_objection": result["any_objection"],
    }


def _aggregate(results: list[dict[str, Any]]) -> dict[str, Any]:
    by_method: dict[str, list[dict[str, Any]]] = {}
    for r in results:
        by_method.setdefault(r["method"], []).append(r)

    summary: dict[str, Any] = {}
    for method, rows in sorted(by_method.items()):
        valid = [r for r in rows if isinstance(r.get("any_objection"), bool)]
        ag1_valid = [r["agent1_has_objection"] for r in rows if isinstance(r.get("agent1_has_objection"), bool)]
        ag2_valid = [r["agent2_has_objection"] for r in rows if isinstance(r.get("agent2_has_objection"), bool)]
        summary[method] = {
            "n": len(rows),
            "no_objection_rate": round(1 - sum(r["any_objection"] for r in valid) / len(valid), 4) if valid else None,
            "agent1_no_objection_rate": round(1 - sum(ag1_valid) / len(ag1_valid), 4) if ag1_valid else None,
            "agent2_no_objection_rate": round(1 - sum(ag2_valid) / len(ag2_valid), 4) if ag2_valid else None,
        }
    return summary


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=None)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument(
        "--trials", type=int, default=1,
        help="method x topic の組ごとに使う試行数（デフォルト1 = 6 topics x 4 methods = 24 logs）",
    )
    args = parser.parse_args()

    model_name = resolve_evaluator_model(args.model)
    log_paths = _collect_logs(args.trials)
    print(f"Evaluating {len(log_paths)} logs for final-answer objections ({model_name}, workers={args.workers}) ...")

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
                    f"ag1={r['agent1_has_objection']} ag2={r['agent2_has_objection']} "
                    f"any={r['any_objection']}",
                    flush=True,
                )
            results.append(r)

    results.sort(key=lambda r: (r["topic"], r["file"]))
    summary = _aggregate(results)

    print()
    print("=" * 70)
    print("FINAL ANSWER OBJECTIONS — SUMMARY BY METHOD")
    print("=" * 70)
    print(f"{'method':<14}{'n':>4}{'no_obj_rate':>14}{'ag1_no_obj':>13}{'ag2_no_obj':>13}")
    for method, agg in summary.items():
        print(
            f"{method:<14}{agg['n']:>4}{agg['no_objection_rate']:>14}"
            f"{agg['agent1_no_objection_rate']:>13}{agg['agent2_no_objection_rate']:>13}"
        )

    OUT_PATH.write_text(
        json.dumps({"summary_by_method": summary, "detail": results}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nSaved: {OUT_PATH}")

    OUT_CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    header = "topic,category,method,agent1_has_objection,agent2_has_objection,any_objection\n"
    lines = [header]
    for r in results:
        lines.append(
            f"{r['topic']},{r['category']},{r['method']},"
            f"{r['agent1_has_objection']},{r['agent2_has_objection']},{r['any_objection']}\n"
        )
    OUT_CSV_PATH.write_text("".join(lines), encoding="utf-8")
    print(f"Saved: {OUT_CSV_PATH}")


if __name__ == "__main__":
    main()
