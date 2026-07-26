"""Constructiveness / Constraint Preservation の新ルーブリックで sweep ディレクトリを一括評価する.

`eval_sweep.py`（既存4軸）と同じ CLI 構造だが、採点ロジックだけ
`evaluation_rubrics.evaluate_rubrics`（軸ごとに別々の LLM 呼び出し）に差し替えている。

Usage:
    python src/eval/eval_sweep_rubrics.py --sweep logs/sweep_all_topics_schema_mini_fixed
    python src/eval/eval_sweep_rubrics.py --sweep logs/sweep_all_topics_schema_mini_fixed --model gpt-5.4-mini
    python src/eval/eval_sweep_rubrics.py --sweep logs/sweep_all_topics_schema_mini_fixed --out results_rubrics.json
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

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv(ROOT / ".env")

from src.eval.evaluation_rubrics import AXES_V2, build_metrics_v2, efficiency_metrics, evaluate_rubrics
from src.eval.run_eval import resolve_evaluator_model


class _EvaluatorModel:
    def __init__(self, model_name: str, reasoning_effort: str | None = None) -> None:
        self.model = model_name
        kwargs: dict[str, Any] = {"model": model_name}
        # GPT-5 系の評価器のみ reasoning_effort を渡す（例: nano を high で採点）。
        if reasoning_effort and model_name.lower().startswith("gpt-5"):
            kwargs["reasoning_effort"] = reasoning_effort
        self._client = ChatOpenAI(**kwargs)

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
    """ログの method/mode フィールドを schema/no_schema/free_debate/mad の4値に正規化する."""
    if method in {"no_schema", "no-schema"}:
        return "no_schema"
    if method in {"free_debate", "mad"}:
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
    """Results を turns x attempts ごとにグループ化して平均を計算する."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for r in results:
        turns_part = f"turns{r['turns']:02d}" if r.get("turns") is not None else "turnsNA"
        attempts_part = f"attempts{r['attempts']:02d}" if r.get("attempts") is not None else "attemptsNA"
        key = f"{turns_part}_{attempts_part}"
        groups.setdefault(key, []).append(r)

    summary: dict[str, dict[str, Any]] = {}
    for group_key, group_results in sorted(groups.items()):
        valid = [
            r for r in group_results
            if any(isinstance(r.get(a), (int, float)) for a in AXES_V2)
        ]
        if not valid:
            summary[group_key] = {"n": len(group_results), "error": "all evaluations failed"}
            continue

        agg: dict[str, Any] = {"n": len(group_results), "n_valid": len(valid)}
        for axis in AXES_V2:
            nums = [float(r[axis]) for r in valid if isinstance(r.get(axis), (int, float))]
            agg[axis] = round(sum(nums) / len(nums), 2) if nums else None

        axis_vals = [agg[a] for a in AXES_V2 if isinstance(agg.get(a), (int, float))]
        agg["quality_average_v2"] = round(sum(axis_vals) / len(axis_vals), 2) if axis_vals else None

        for eff_key in ("elapsed_seconds", "total_cost_usd", "total_tokens"):
            nums = [float(r[eff_key]) for r in valid if isinstance(r.get(eff_key), (int, float))]
            agg[eff_key] = round(sum(nums) / len(nums), 2) if nums else None

        summary[group_key] = agg

    return summary


def _print_summary(summary: dict[str, dict[str, Any]], all_results: list[dict[str, Any]]) -> None:
    print()
    print("=" * 60)
    print("SWEEP EVALUATION SUMMARY (Constructiveness / Constraint Preservation)")
    print("=" * 60)
    print(f"{'Group':<14} {'Constr':>7} {'ConstrPres':>11} {'Avg':>6}  {'Time(s)':>8}  {'Cost($)':>8}  {'Tokens':>8}  n")
    print("-" * 90)

    for group_key, agg in sorted(summary.items()):
        if "error" in agg:
            print(f"{group_key:<14}  (evaluation failed, n={agg['n']})")
            continue

        def _f(v: Any, fmt: str = ".2f") -> str:
            return f"{v:{fmt}}" if isinstance(v, (int, float)) else "N/A"

        print(
            f"{group_key:<14}"
            f" {_f(agg.get('constructiveness')):>7}"
            f" {_f(agg.get('constraint_preservation')):>11}"
            f" {_f(agg.get('quality_average_v2')):>6}"
            f"  {_f(agg.get('elapsed_seconds'), '.1f'):>8}"
            f"  {_f(agg.get('total_cost_usd'), '.4f'):>8}"
            f"  {_f(agg.get('total_tokens'), '.0f'):>8}"
            f"  {agg['n_valid']}/{agg['n']}"
        )

    print()
    print("Per-run results:")
    print(f"{'Folder':<30} {'Constr':>7} {'ConstrPres':>11}")
    print("-" * 50)
    for r in all_results:
        def _f2(v: Any) -> str:
            return f"{v:.2f}" if isinstance(v, (int, float)) else " N/A"
        print(
            f"{r['folder']:<30}"
            f" {_f2(r.get('constructiveness')):>7}"
            f" {_f2(r.get('constraint_preservation')):>11}"
        )
    print()


def _evaluate_entry(
    entry: tuple[str, Path],
    model_name: str,
    sweep_dir: Path,
    reasoning_effort: str | None = None,
) -> dict[str, Any]:
    """1ファイル分を評価する（呼び出し元がスレッドごとに独立した evaluator を渡す）."""
    folder, log_path = entry
    turns = _parse_turns(folder)
    log = json.loads(log_path.read_text(encoding="utf-8"))
    mode = _normalize_method(log.get("method") or log.get("mode"))
    evaluator = _EvaluatorModel(model_name, reasoning_effort)
    scores = evaluate_rubrics(log, evaluator)
    metrics = build_metrics_v2(scores, efficiency_metrics(log))
    return {
        "folder": folder,
        "log_file": str(log_path.relative_to(sweep_dir)),
        "turns": turns,
        "attempts": _parse_attempts(folder),
        "method": mode,
        **metrics,
    }


def _run_group(
    combo_key: str,
    group_entries: list[tuple[str, Path]],
    model_name: str,
    sweep_dir: Path,
    progress_lock: threading.Lock,
    counter: list[int],
    reasoning_effort: str | None = None,
) -> list[dict[str, Any]]:
    """1つのコンボディレクトリ（turnsXX_attemptsYY、複数トピック）を直列に評価する。グループ間は呼び出し元が並列化する."""
    results = []
    for entry in group_entries:
        result = _evaluate_entry(entry, model_name, sweep_dir, reasoning_effort)
        with progress_lock:
            counter[0] += 1
            print(
                f"[{counter[0]:03d}/{counter[1]}] ({combo_key}) {result['folder']} ... "
                f"constructiveness={result.get('constructiveness')} "
                f"constraint_preservation={result.get('constraint_preservation')}",
                flush=True,
            )
        results.append(result)
    return results


def main() -> None:
    """Sweep ディレクトリ配下の全ログを新ルーブリックで評価し、結果をまとめて出力する."""
    parser = argparse.ArgumentParser(
        description="Batch-evaluate all logs under a sweep directory with the Constructiveness / "
        "Constraint Preservation rubric."
    )
    parser.add_argument("--sweep", required=True, help="Path to the sweep directory.")
    parser.add_argument("--model", default=None, help="Evaluator model name.")
    parser.add_argument(
        "--reasoning-effort",
        default=None,
        help="評価器の reasoning_effort（GPT-5系のみ有効。例: nano を high で採点）。",
    )
    parser.add_argument("--out", default=None, help="Path to save full results JSON.")
    parser.add_argument(
        "--method",
        choices=("schema", "no_schema", "free_debate", "mad"),
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

    effort_note = f" effort={args.reasoning_effort}" if args.reasoning_effort else ""
    print(f"Evaluating {len(entries)} logs with {model_name}{effort_note} (Constructiveness / Constraint Preservation) ...")
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
                _run_group(
                    combo_key, group_entries, model_name, sweep_dir,
                    progress_lock, counter, args.reasoning_effort,
                )
            )
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(
                    _run_group, combo_key, group_entries, model_name, sweep_dir,
                    progress_lock, counter, args.reasoning_effort,
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
        default_out = sweep_dir / "eval_results_rubrics.json"
        default_out.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Results saved to {default_out}")


if __name__ == "__main__":
    main()
