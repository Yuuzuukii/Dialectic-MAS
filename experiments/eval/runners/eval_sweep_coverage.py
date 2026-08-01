"""スタンス項目のカバレッジ率（反映された項目数/総項目数）で sweep ディレクトリを一括評価する.

`eval_sweep_rubrics.py`（holisticな1〜10スコア）と同じCLI構造だが、採点ロジックだけ
`evaluation_coverage.evaluate_stance_coverage`（スタンスから機械的に切り出した項目
ごとに、最終回答で反映されているかを構造化出力で判定し、カバレッジ率を算出）に
差し替えている。

Usage:
    python -m experiments.eval.runners.eval_sweep_coverage --sweep logs/synthesis_comparison_full/schema_synthesis
    python -m experiments.eval.runners.eval_sweep_coverage --sweep <dir> --workers 11
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

from experiments.eval.scoring.evaluation_coverage import evaluate_stance_coverage
from experiments.eval.runners.run_eval import resolve_evaluator_model


class _EvaluatorModel:
    def __init__(self, model_name: str) -> None:
        self.model = model_name
        self._client = ChatOpenAI(model=model_name)

    def invoke(self, prompt: str) -> str:
        response = self._client.invoke(prompt)
        content = response.content
        if isinstance(content, str):
            return content
        return "\n".join(str(part) for part in content)


def _parse_turns(folder_name: str) -> int | None:
    """turnsXX_attemptsYY からターン数を抽出する."""
    m = re.match(r"turns(\d+)_attempts\d+", folder_name)
    return int(m.group(1)) if m else None


def _parse_attempts(folder_name: str) -> int | None:
    """turnsXX_attemptsYY から main argument 試行回数上限を抽出する."""
    m = re.match(r"turns\d+_attempts(\d+)", folder_name)
    return int(m.group(1)) if m else None


def _normalize_method(method: str | None) -> str:
    """ログの method/mode フィールドを既知の5値に正規化する."""
    if method in {"no_schema", "no-schema"}:
        return "no_schema"
    if method in {"free_debate", "mad", "mad_synthesis"}:
        return method
    return "schema"


def _collect_logs(sweep_dir: Path) -> list[tuple[str, Path]]:
    """sweepディレクトリ配下のJSONファイルを (フォルダ名, パス) のリストで返す.

    sweep_dir 直下のファイル（eval_results*.json 等の集計ファイル）は除外する。
    """
    entries: list[tuple[str, Path]] = []
    for json_path in sorted(sweep_dir.rglob("*.json")):
        rel = json_path.relative_to(sweep_dir)
        if len(rel.parts) < 2:
            continue
        folder = rel.parts[0]
        entries.append((folder, json_path))
    return entries


def _aggregate_by_group(results: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Results を turns x attempts ごとにグループ化して平均カバレッジ率を計算する."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for r in results:
        turns_part = f"turns{r['turns']:02d}" if r.get("turns") is not None else "turnsNA"
        attempts_part = f"attempts{r['attempts']:02d}" if r.get("attempts") is not None else "attemptsNA"
        key = f"{turns_part}_{attempts_part}"
        groups.setdefault(key, []).append(r)

    summary: dict[str, dict[str, Any]] = {}
    for group_key, group_results in sorted(groups.items()):
        valid = [r for r in group_results if isinstance(r.get("ratio"), (int, float))]
        if not valid:
            summary[group_key] = {"n": len(group_results), "error": "all evaluations failed"}
            continue

        ratios = [float(r["ratio"]) for r in valid]
        summary[group_key] = {
            "n": len(group_results),
            "n_valid": len(valid),
            "coverage_ratio": round(sum(ratios) / len(ratios), 4),
        }
    return summary


def _print_summary(summary: dict[str, dict[str, Any]], all_results: list[dict[str, Any]]) -> None:
    print()
    print("=" * 60)
    print("SWEEP EVALUATION SUMMARY (Stance Coverage Ratio)")
    print("=" * 60)
    print(f"{'Group':<18} {'CoverageRatio':>13}  n")
    print("-" * 45)
    for group_key, agg in sorted(summary.items()):
        if "error" in agg:
            print(f"{group_key:<18}  (evaluation failed, n={agg['n']})")
            continue
        print(f"{group_key:<18} {agg['coverage_ratio']:>13.3f}  {agg['n_valid']}/{agg['n']}")

    print()
    print("Per-run results:")
    print(f"{'Folder':<20} {'covered/total':>14} {'ratio':>7}")
    print("-" * 45)
    for r in all_results:
        cov = r.get("covered")
        total = r.get("total")
        ratio = r.get("ratio")
        cov_str = f"{cov}/{total}" if cov is not None else "N/A"
        ratio_str = f"{ratio:.3f}" if isinstance(ratio, (int, float)) else " N/A"
        print(f"{r['folder']:<20} {cov_str:>14} {ratio_str:>7}")
    print()


def _evaluate_entry(
    entry: tuple[str, Path],
    model_name: str,
    sweep_dir: Path,
) -> dict[str, Any]:
    """1ファイル分を評価する（呼び出し元がスレッドごとに独立した evaluator を渡す）."""
    folder, log_path = entry
    turns = _parse_turns(folder)
    log = json.loads(log_path.read_text(encoding="utf-8"))
    mode = _normalize_method(log.get("method") or log.get("mode"))
    evaluator = _EvaluatorModel(model_name)
    result = evaluate_stance_coverage(log, evaluator)
    return {
        "folder": folder,
        "log_file": str(log_path.relative_to(sweep_dir)),
        "turns": turns,
        "attempts": _parse_attempts(folder),
        "method": mode,
        "covered": result["covered"],
        "total": result["total"],
        "ratio": result["ratio"],
    }


def _run_group(
    combo_key: str,
    group_entries: list[tuple[str, Path]],
    model_name: str,
    sweep_dir: Path,
    progress_lock: threading.Lock,
    counter: list[int],
) -> list[dict[str, Any]]:
    """1つのコンボディレクトリ（turnsXX_attemptsYY、複数トピック）を直列に評価する。グループ間は呼び出し元が並列化する."""
    results = []
    for entry in group_entries:
        result = _evaluate_entry(entry, model_name, sweep_dir)
        with progress_lock:
            counter[0] += 1
            print(
                f"[{counter[0]:03d}/{counter[1]}] ({combo_key}) {result['folder']} ... "
                f"covered={result.get('covered')}/{result.get('total')} ratio={result.get('ratio')}",
                flush=True,
            )
        results.append(result)
    return results


def main() -> None:
    """Sweep ディレクトリ配下の全ログをスタンスカバレッジ率で評価し、結果をまとめて出力する."""
    parser = argparse.ArgumentParser(
        description="Batch-evaluate all logs under a sweep directory with the stance coverage ratio."
    )
    parser.add_argument("--sweep", required=True, help="Path to the sweep directory.")
    parser.add_argument("--model", default=None, help="Evaluator model name.")
    parser.add_argument("--out", default=None, help="Path to save full results JSON.")
    parser.add_argument(
        "--method",
        choices=("schema", "no_schema", "free_debate", "mad", "mad_synthesis"),
        default=None,
        help="指定すると、その手法のログだけを評価する（未指定なら sweep 配下の全手法を評価）。",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="attempts グループ単位の並列ワーカー数（既定1=直列）。sweep内の attempts 値の種類数が上限。",
    )
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

    print(f"Evaluating {len(entries)} logs with {model_name} (Stance Coverage Ratio) ...")
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
    _print_summary(summary, all_results)

    output = {"summary_by_turns": summary, "per_run": all_results}
    if args.out:
        out_path = Path(args.out)
        if not out_path.is_absolute():
            out_path = ROOT / out_path
        out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Results saved to {out_path}")
    else:
        default_out = sweep_dir / "eval_results_coverage.json"
        default_out.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Results saved to {default_out}")


if __name__ == "__main__":
    main()
