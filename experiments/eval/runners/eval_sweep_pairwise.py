"""ペア単位（対象1発言 + 応答1発言）で Constructiveness を採点し、集計する.

`eval_sweep_rubrics.py` と同じ CLI 構造だが、採点ロジックだけ
`evaluation_pairwise.evaluate_pairwise_constructiveness`（ログ1件につき、
含まれる全ペアを個別採点してから平均する）に差し替えている。

Usage:
    python src/eval/eval_sweep_pairwise.py --sweep logs/sweep_all_topics_schema_nano_unified
    python src/eval/eval_sweep_pairwise.py --sweep logs/... --model gpt-5.4-mini --out results.json
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

from experiments.eval.scoring.evaluation_pairwise import evaluate_pairwise_constructiveness
from experiments.eval.scoring.evaluation import efficiency_metrics
from experiments.eval.runners.run_eval import resolve_evaluator_model


class _EvaluatorModel:
    def __init__(self, model_name: str) -> None:
        self.model = model_name
        self._client = ChatOpenAI(model=model_name)

    def invoke(self, prompt: str) -> str:
        response = self._client.invoke(prompt)
        content = response.content
        return content if isinstance(content, str) else "\n".join(str(p) for p in content)


def _parse_turns(folder_name: str) -> int | None:
    m = re.match(r"turns(\d+)_attempts\d+", folder_name)
    return int(m.group(1)) if m else None


def _parse_attempts(folder_name: str) -> int | None:
    m = re.match(r"turns\d+_attempts(\d+)", folder_name)
    return int(m.group(1)) if m else None


def _normalize_method(method: str | None) -> str:
    if method in {"no_schema", "no-schema"}:
        return "no_schema"
    if method in {"free_debate", "mad"}:
        return method
    return "schema"


def _collect_logs(sweep_dir: Path) -> list[tuple[str, Path]]:
    entries: list[tuple[str, Path]] = []
    for json_path in sorted(sweep_dir.rglob("*.json")):
        rel = json_path.relative_to(sweep_dir)
        if len(rel.parts) < 2:
            continue
        entries.append((rel.parts[0], json_path))
    return entries


def _evaluate_entry(
    entry: tuple[str, Path], model_name: str, sweep_dir: Path
) -> dict[str, Any]:
    folder, log_path = entry
    turns = _parse_turns(folder)
    log = json.loads(log_path.read_text(encoding="utf-8"))
    mode = _normalize_method(log.get("method") or log.get("mode"))
    evaluator = _EvaluatorModel(model_name)
    result = evaluate_pairwise_constructiveness(log, evaluator)
    eff = efficiency_metrics(log)
    return {
        "folder": folder,
        "log_file": str(log_path.relative_to(sweep_dir)),
        "turns": turns,
        "attempts": _parse_attempts(folder),
        "method": mode,
        "pairwise_constructiveness": result["pairwise_constructiveness"],
        "n_pairs": result["n_pairs"],
        **eff,
    }


def _aggregate_by_group(results: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for r in results:
        turns_part = f"turns{r['turns']:02d}" if r.get("turns") is not None else "turnsNA"
        attempts_part = (
            f"attempts{r['attempts']:02d}" if r.get("attempts") is not None else "attemptsNA"
        )
        key = f"{turns_part}_{attempts_part}"
        groups.setdefault(key, []).append(r)

    summary: dict[str, dict[str, Any]] = {}
    for group_key, group_results in sorted(groups.items()):
        valid = [
            r for r in group_results if isinstance(r.get("pairwise_constructiveness"), (int, float))
        ]
        if not valid:
            summary[group_key] = {"n": len(group_results), "error": "all evaluations failed"}
            continue
        nums = [float(r["pairwise_constructiveness"]) for r in valid]
        n_pairs = [r["n_pairs"] for r in valid]
        summary[group_key] = {
            "n": len(group_results),
            "n_valid": len(valid),
            "pairwise_constructiveness": round(sum(nums) / len(nums), 3),
            "avg_n_pairs": round(sum(n_pairs) / len(n_pairs), 2),
        }
    return summary


def _run_group(
    combo_key: str,
    group_entries: list[tuple[str, Path]],
    model_name: str,
    sweep_dir: Path,
    progress_lock: threading.Lock,
    counter: list[int],
) -> list[dict[str, Any]]:
    results = []
    for entry in group_entries:
        result = _evaluate_entry(entry, model_name, sweep_dir)
        with progress_lock:
            counter[0] += 1
            print(
                f"[{counter[0]:03d}/{counter[1]}] ({combo_key}) {result['folder']} "
                f"n_pairs={result['n_pairs']} ... avg={result.get('pairwise_constructiveness')}",
                flush=True,
            )
        results.append(result)
    return results


def main() -> None:
    """ペア単位 Constructiveness 評価の CLI エントリポイント."""
    parser = argparse.ArgumentParser(description="Batch-evaluate pairwise constructiveness.")
    parser.add_argument("--sweep", required=True, help="Path to the sweep directory.")
    parser.add_argument("--model", default=None, help="Evaluator model name.")
    parser.add_argument("--out", default=None, help="Path to save full results JSON.")
    parser.add_argument(
        "--method",
        choices=("schema", "no_schema", "free_debate", "mad"),
        default=None,
    )
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()

    model_name = resolve_evaluator_model(args.model)
    sweep_dir = Path(args.sweep)
    if not sweep_dir.is_absolute():
        sweep_dir = ROOT / sweep_dir
    if not sweep_dir.exists():
        print(f"Sweep directory not found: {sweep_dir}", file=sys.stderr)
        sys.exit(1)

    entries = _collect_logs(sweep_dir)
    if args.method:
        entries = [
            (folder, log_path)
            for folder, log_path in entries
            if _normalize_method(
                json.loads(log_path.read_text(encoding="utf-8")).get("method")
                or json.loads(log_path.read_text(encoding="utf-8")).get("mode")
            )
            == args.method
        ]
    if not entries:
        print(f"No JSON files found under {sweep_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"Evaluating {len(entries)} logs (pairwise) with {model_name} ...")
    print(f"Sweep: {sweep_dir}" + (f" (method={args.method})" if args.method else ""))

    groups: dict[str, list[tuple[str, Path]]] = {}
    for folder, log_path in entries:
        groups.setdefault(folder, []).append((folder, log_path))

    workers = max(1, min(args.workers, len(groups)))
    print(f"Combo groups: {sorted(groups)}  workers={workers}")
    print()

    all_results: list[dict[str, Any]] = []
    progress_lock = threading.Lock()
    counter = [0, len(entries)]

    if workers == 1:
        for combo_key, group_entries in sorted(groups.items()):
            all_results.extend(
                _run_group(combo_key, group_entries, model_name, sweep_dir, progress_lock, counter)
            )
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(
                    _run_group, combo_key, group_entries, model_name, sweep_dir, progress_lock, counter
                ): combo_key
                for combo_key, group_entries in groups.items()
            }
            for future in as_completed(futures):
                all_results.extend(future.result())

    all_results.sort(key=lambda r: r["folder"])
    summary = _aggregate_by_group(all_results)

    print()
    print("=" * 60)
    print("PAIRWISE CONSTRUCTIVENESS SUMMARY")
    print("=" * 60)
    for group_key, agg in sorted(summary.items()):
        if "error" in agg:
            print(f"{group_key:<14}  (evaluation failed, n={agg['n']})")
            continue
        print(
            f"{group_key:<14} pairwise_constructiveness={agg['pairwise_constructiveness']:.3f}"
            f"  avg_n_pairs={agg['avg_n_pairs']:.2f}  n={agg['n_valid']}/{agg['n']}"
        )

    output = {"summary_by_turns": summary, "per_run": all_results}
    if args.out:
        out_path = Path(args.out)
        if not out_path.is_absolute():
            out_path = ROOT / out_path
        out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Results saved to {out_path}")
    else:
        default_out = sweep_dir / "eval_results_pairwise.json"
        default_out.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Results saved to {default_out}")


if __name__ == "__main__":
    main()
