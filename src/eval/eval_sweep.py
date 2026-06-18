"""Batch-evaluate all logs under a sweep directory and summarize scores by turns setting.

Usage:
    python src/eval/eval_sweep.py --sweep logs/sweep/artificial_intelligence_20260616_011149
    python src/eval/eval_sweep.py --sweep logs/sweep/artificial_intelligence_20260616_011149 --model gpt-4o
    python src/eval/eval_sweep.py --sweep logs/sweep/artificial_intelligence_20260616_011149 --out results.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv(ROOT / ".env")

from src.eval.evaluation import AXES, build_eval_input, efficiency_metrics, evaluate_with_llm
from src.eval.run_eval import _build_metrics, resolve_evaluator_model


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


def _collect_logs(sweep_dir: Path) -> list[tuple[str, Path]]:
    """sweepディレクトリ配下のJSONファイルを (フォルダ名, パス) のリストで返す.

    sweep_dir 直下のファイル（eval_results.json 等の集計ファイル）は除外する。
    """
    entries: list[tuple[str, Path]] = []
    for json_path in sorted(sweep_dir.rglob("*.json")):
        rel = json_path.relative_to(sweep_dir)
        if len(rel.parts) < 2:
            # sweep_dir 直下のファイルはスキップ（eval_results.json 等）
            continue
        folder = rel.parts[0]
        entries.append((folder, json_path))
    return entries


def _aggregate_by_group(
    results: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """results を turns ごとにグループ化して平均を計算する."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for r in results:
        key = f"turns{r['turns']:02d}"
        groups.setdefault(key, []).append(r)

    summary: dict[str, dict[str, Any]] = {}
    for group_key, group_results in sorted(groups.items()):
        valid = [r for r in group_results if r.get("quality_average") is not None]
        if not valid:
            summary[group_key] = {"n": len(group_results), "error": "all evaluations failed"}
            continue

        agg: dict[str, Any] = {"n": len(group_results), "n_valid": len(valid)}
        for axis in AXES:
            nums = [float(r[axis]) for r in valid if isinstance(r.get(axis), (int, float))]
            agg[axis] = round(sum(nums) / len(nums), 2) if nums else None

        axis_vals = [agg[a] for a in AXES if isinstance(agg.get(a), (int, float))]
        agg["quality_average"] = round(sum(axis_vals) / len(axis_vals), 2) if axis_vals else None

        for eff_key in ("elapsed_seconds", "total_cost_usd", "total_tokens"):
            nums = [float(r[eff_key]) for r in valid if isinstance(r.get(eff_key), (int, float))]
            agg[eff_key] = round(sum(nums) / len(nums), 2) if nums else None

        summary[group_key] = agg

    return summary


def _print_summary(summary: dict[str, dict[str, Any]], all_results: list[dict[str, Any]]) -> None:
    print()
    print("=" * 60)
    print("SWEEP EVALUATION SUMMARY")
    print("=" * 60)
    print(f"{'Group':<14} {'Coh':>5} {'Ori':>5} {'Dia':>5} {'Val':>5} {'Avg':>5}  {'Time(s)':>8}  {'Cost($)':>8}  {'Tokens':>8}  n")
    print("-" * 90)

    for group_key, agg in sorted(summary.items()):
        if "error" in agg:
            print(f"{group_key:<14}  (evaluation failed, n={agg['n']})")
            continue

        def _f(v: Any, fmt: str = ".2f") -> str:
            return f"{v:{fmt}}" if isinstance(v, (int, float)) else "N/A"

        print(
            f"{group_key:<14}"
            f" {_f(agg.get('coherence')):>5}"
            f" {_f(agg.get('originality')):>5}"
            f" {_f(agg.get('dialecticality')):>5}"
            f" {_f(agg.get('validity')):>5}"
            f" {_f(agg.get('quality_average')):>5}"
            f"  {_f(agg.get('elapsed_seconds'), '.1f'):>8}"
            f"  {_f(agg.get('total_cost_usd'), '.4f'):>8}"
            f"  {_f(agg.get('total_tokens'), '.0f'):>8}"
            f"  {agg['n_valid']}/{agg['n']}"
        )

    print()
    print("Per-run results:")
    print(f"{'Folder':<30} {'Coh':>5} {'Ori':>5} {'Dia':>5} {'Val':>5} {'Avg':>5}")
    print("-" * 60)
    for r in all_results:
        def _f2(v: Any) -> str:
            return f"{v:.2f}" if isinstance(v, (int, float)) else " N/A"
        print(
            f"{r['folder']:<30}"
            f" {_f2(r.get('coherence')):>5}"
            f" {_f2(r.get('originality')):>5}"
            f" {_f2(r.get('dialecticality')):>5}"
            f" {_f2(r.get('validity')):>5}"
            f" {_f2(r.get('quality_average')):>5}"
        )
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch-evaluate all logs under a sweep directory.")
    parser.add_argument("--sweep", required=True, help="Path to the sweep directory.")
    parser.add_argument("--model", default=None, help="Evaluator model name.")
    parser.add_argument("--out", default=None, help="Path to save full results JSON.")
    args = parser.parse_args()

    model_name = resolve_evaluator_model(args.model)
    sweep_dir = Path(args.sweep)
    if not sweep_dir.is_absolute():
        sweep_dir = ROOT / sweep_dir
    if not sweep_dir.exists():
        print(f"Sweep directory not found: {sweep_dir}", file=sys.stderr)
        sys.exit(1)

    entries = _collect_logs(sweep_dir)
    if not entries:
        print(f"No JSON files found under {sweep_dir}", file=sys.stderr)
        sys.exit(1)

    evaluator = _EvaluatorModel(model_name)
    print(f"Evaluating {len(entries)} logs with {model_name} ...")
    print(f"Sweep: {sweep_dir}")
    print()

    all_results: list[dict[str, Any]] = []

    for i, (folder, log_path) in enumerate(entries, 1):
        turns = _parse_turns(folder)
        print(f"[{i:02d}/{len(entries)}] {folder} ...", end=" ", flush=True)

        log = json.loads(log_path.read_text(encoding="utf-8"))
        method = log.get("method") or log.get("mode")
        mode = "no_schema" if method in {"no_schema", "no-schema"} else "schema"
        eval_input = build_eval_input(log, mode=mode)
        scores = evaluate_with_llm(eval_input, evaluator)
        metrics = _build_metrics(scores, efficiency_metrics(log))

        result: dict[str, Any] = {
            "folder": folder,
            "log_file": str(log_path.relative_to(sweep_dir)),
            "turns": turns,
            **metrics,
        }
        all_results.append(result)

        avg = metrics.get("quality_average")
        print(f"avg={avg}")

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
        default_out = sweep_dir / "eval_results.json"
        default_out.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Results saved to {default_out}")


if __name__ == "__main__":
    main()
