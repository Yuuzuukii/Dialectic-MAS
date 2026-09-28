"""logs/final_gpt54nano_turns10 配下の全120ログを再評価する.

細分化(atomic)カバレッジで再評価し、既存(final_comparison.json)のスタンス行
ベースのカバレッジと比較する。

- 新項目抽出: stance_decomposition.extract_stance_items_atomic（spaCy依存構造解析、LLM不要・決定論的）
- 判定: evaluation_coverage_atomic.evaluate_stance_coverage_atomic（項目ごと独立LLM呼び出し、既存と同じ判定ロジック）
- 旧カバレッジは再評価せず、logs/final_gpt54nano_turns10/final_comparison.json の値をそのまま再利用する
  （コスト削減、かつ「評価をまるっと変えない」という方針に合わせ、旧指標はそのまま比較対象として保持）。

Usage:
    python -m experiments.eval.runners.eval_atomic_coverage_final
    python -m experiments.eval.runners.eval_atomic_coverage_final --workers 8
"""

# ruff: noqa: T201, E402, I001

from __future__ import annotations

import argparse
import json
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
from experiments.eval.scoring.evaluation_coverage_atomic import evaluate_stance_coverage_atomic

LOGS_DIR = ROOT / "logs" / "final_gpt54nano_turns10"
OLD_COMPARISON_PATH = LOGS_DIR / "final_comparison.json"
OUT_PATH = LOGS_DIR / "atomic_coverage_comparison.json"
OUT_CSV_PATH = ROOT / "docs" / "results" / "atomic_coverage_comparison.csv"


class _EvaluatorModel:
    def __init__(self, model_name: str) -> None:
        self.model = model_name
        self._client = ChatOpenAI(model=model_name)

    def invoke(self, prompt: str) -> str:
        response = self._client.invoke(prompt)
        content = response.content
        return content if isinstance(content, str) else "\n".join(str(p) for p in content)


def _load_old_ratios() -> dict[str, dict[str, Any]]:
    data = json.loads(OLD_COMPARISON_PATH.read_text(encoding="utf-8"))
    return {entry["file"]: entry for entry in data["detail"]}


def _collect_logs() -> list[Path]:
    return sorted(LOGS_DIR.glob("*/*/*.json"))


def _evaluate_one(log_path: Path, model_name: str, old_by_file: dict[str, dict[str, Any]]) -> dict[str, Any]:
    log = json.loads(log_path.read_text(encoding="utf-8"))
    evaluator = _EvaluatorModel(model_name)
    result = evaluate_stance_coverage_atomic(log, evaluator)
    old = old_by_file.get(log_path.name, {})
    return {
        "file": log_path.name,
        "topic": log_path.parent.name,
        "category": log_path.parent.parent.name,
        "method": log.get("method") or log.get("mode"),
        "old_covered": old.get("coverage_covered"),
        "old_total": old.get("coverage_total"),
        "old_ratio": old.get("coverage_ratio"),
        "atomic_covered": result["covered"],
        "atomic_total": result["total"],
        "atomic_ratio": result["ratio"],
    }


def _aggregate(results: list[dict[str, Any]]) -> dict[str, Any]:
    by_method: dict[str, list[dict[str, Any]]] = {}
    for r in results:
        by_method.setdefault(r["method"], []).append(r)

    summary: dict[str, Any] = {}
    for method, rows in sorted(by_method.items()):
        old_valid = [r["old_ratio"] for r in rows if isinstance(r.get("old_ratio"), (int, float))]
        new_valid = [r["atomic_ratio"] for r in rows if isinstance(r.get("atomic_ratio"), (int, float))]
        new_totals = [r["atomic_total"] for r in rows if isinstance(r.get("atomic_total"), (int, float))]
        summary[method] = {
            "n": len(rows),
            "old_coverage_mean": round(sum(old_valid) / len(old_valid), 4) if old_valid else None,
            "atomic_coverage_mean": round(sum(new_valid) / len(new_valid), 4) if new_valid else None,
            "atomic_items_mean": round(sum(new_totals) / len(new_totals), 2) if new_totals else None,
        }
    return summary


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=None)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()

    model_name = resolve_evaluator_model(args.model)
    old_by_file = _load_old_ratios()
    log_paths = _collect_logs()
    print(f"Evaluating {len(log_paths)} logs with atomic coverage ({model_name}, workers={args.workers}) ...")

    results: list[dict[str, Any]] = []
    lock = threading.Lock()
    counter = [0]

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(_evaluate_one, log_path, model_name, old_by_file): log_path
            for log_path in log_paths
        }
        for future in as_completed(futures):
            r = future.result()
            with lock:
                counter[0] += 1
                print(
                    f"[{counter[0]:03d}/{len(log_paths)}] {r['topic']}/{r['file']} "
                    f"old={r['old_ratio']} atomic={r['atomic_ratio']} "
                    f"({r['atomic_covered']}/{r['atomic_total']})",
                    flush=True,
                )
            results.append(r)

    results.sort(key=lambda r: (r["topic"], r["file"]))
    summary = _aggregate(results)

    print()
    print("=" * 70)
    print("ATOMIC COVERAGE vs OLD COVERAGE — SUMMARY BY METHOD")
    print("=" * 70)
    print(f"{'method':<14}{'n':>4}{'old_mean':>12}{'atomic_mean':>14}{'atomic_items':>15}")
    for method, agg in summary.items():
        print(
            f"{method:<14}{agg['n']:>4}{agg['old_coverage_mean']:>12}"
            f"{agg['atomic_coverage_mean']:>14}{agg['atomic_items_mean']:>15}"
        )

    OUT_PATH.write_text(
        json.dumps({"summary_by_method": summary, "detail": results}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nSaved: {OUT_PATH}")

    OUT_CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    header = "topic,category,method,old_ratio,atomic_ratio,atomic_covered,atomic_total\n"
    lines = [header]
    for r in results:
        lines.append(
            f"{r['topic']},{r['category']},{r['method']},{r['old_ratio']},"
            f"{r['atomic_ratio']},{r['atomic_covered']},{r['atomic_total']}\n"
        )
    OUT_CSV_PATH.write_text("".join(lines), encoding="utf-8")
    print(f"Saved: {OUT_CSV_PATH}")


if __name__ == "__main__":
    main()
