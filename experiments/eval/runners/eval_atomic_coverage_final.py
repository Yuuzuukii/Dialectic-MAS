"""Evaluate debate logs with atomic stance coverage.

An optional overlay directory can replace matching base logs. This is useful after
re-finalizing schema/no_schema while keeping free_debate and mad unchanged.

The legacy coverage columns are filled only when --old-comparison (a historical
final_comparison.json) is given; otherwise they stay empty.

Examples:
    python -m experiments.eval.runners.eval_atomic_coverage_final --workers 8
    python -m experiments.eval.runners.eval_atomic_coverage_final \
      --base-dir logs/experiment_20260916_020350/raw_dialogue \
      --out logs/experiment_20260916_020350/eval_result/atomic_coverage/atomic_coverage_comparison.json
"""

# ruff: noqa: T201, E402, I001

from __future__ import annotations

import argparse
import json
import os
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
from experiments.eval.scoring.evaluation_coverage_atomic import evaluate_stance_coverage_atomic

EXPERIMENT_DIR = ROOT / "logs" / "experiment_20260916_020350"
DEFAULT_BASE_DIR = EXPERIMENT_DIR / "raw_dialogue"
DEFAULT_OLD_COMPARISON: Path | None = None
DEFAULT_OUT = EXPERIMENT_DIR / "eval_result" / "atomic_coverage" / "atomic_coverage_comparison.json"
# run 番号の接頭辞 NN_ は任意（--runs 1 のログには付かない）。
_FILENAME_RE = re.compile(r"^(?:\d+_)?(?P<method>.+)_\d{8}_\d{6}_\d+$")


class _EvaluatorModel:
    def __init__(self, model_name: str) -> None:
        self.model = model_name
        self._client = ChatOpenAI(model=model_name)

    def invoke(self, prompt: str) -> str:
        response = self._client.invoke(prompt)
        content = response.content
        return content if isinstance(content, str) else "\n".join(str(p) for p in content)


def _load_old_ratios(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None or not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {entry["file"]: entry for entry in data.get("detail", [])}


def method_allowed(stem: str) -> bool:
    """Return True when the log's method (from its file name) is selected by ``EVAL_METHODS``.

    ``EVAL_METHODS=schema,no_schema`` limits every evaluation runner to those methods, so logs that
    were only copied (and already evaluated before) are not paid for twice. Unset means all methods.
    """
    selected = {m.strip() for m in os.getenv("EVAL_METHODS", "").split(",") if m.strip()}
    if not selected:
        return True
    match = _FILENAME_RE.match(stem)
    return match is not None and match.group("method") in selected


def _relative_log_map(root: Path) -> dict[Path, Path]:
    return {
        path.relative_to(root): path
        for path in sorted(root.glob("*/*/*.json"))
        if _FILENAME_RE.match(path.stem) and method_allowed(path.stem)
    }


def _collect_logs(base_dir: Path, overlay_dir: Path | None) -> list[Path]:
    merged = _relative_log_map(base_dir)
    if overlay_dir is not None:
        if not overlay_dir.exists():
            raise FileNotFoundError(f"Overlay directory does not exist: {overlay_dir}")
        merged.update(_relative_log_map(overlay_dir))
    return [path for _, path in sorted(merged.items())]


def _evaluate_one(
    log_path: Path,
    model_name: str,
    old_by_file: dict[str, dict[str, Any]],
) -> dict[str, Any]:
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
    for row in results:
        by_method.setdefault(row["method"], []).append(row)

    summary: dict[str, Any] = {}
    for method, rows in sorted(by_method.items()):
        old_valid = [
            row["old_ratio"]
            for row in rows
            if isinstance(row.get("old_ratio"), (int, float))
        ]
        new_valid = [
            row["atomic_ratio"]
            for row in rows
            if isinstance(row.get("atomic_ratio"), (int, float))
        ]
        new_totals = [
            row["atomic_total"]
            for row in rows
            if isinstance(row.get("atomic_total"), (int, float))
        ]
        summary[method] = {
            "n": len(rows),
            "old_coverage_mean": (
                round(sum(old_valid) / len(old_valid), 4) if old_valid else None
            ),
            "atomic_coverage_mean": (
                round(sum(new_valid) / len(new_valid), 4) if new_valid else None
            ),
            "atomic_items_mean": (
                round(sum(new_totals) / len(new_totals), 2) if new_totals else None
            ),
        }
    return summary


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=None)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--base-dir", type=Path, default=DEFAULT_BASE_DIR)
    parser.add_argument(
        "--overlay-dir",
        type=Path,
        default=None,
        help="Optional log root whose matching relative paths replace base logs.",
    )
    parser.add_argument(
        "--old-comparison",
        type=Path,
        default=DEFAULT_OLD_COMPARISON,
        help="Historical final_comparison.json used only for legacy coverage columns.",
    )
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--csv-out", type=Path, default=None)
    args = parser.parse_args()

    base_dir = args.base_dir.resolve()
    overlay_dir = args.overlay_dir.resolve() if args.overlay_dir is not None else None
    out_path = (
        args.out.resolve()
        if args.out is not None
        else (
            overlay_dir / "atomic_coverage_comparison.json"
            if overlay_dir is not None
            else DEFAULT_OUT
        )
    )
    csv_out_path = (
        args.csv_out.resolve()
        if args.csv_out is not None
        else out_path.with_suffix(".csv")
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    csv_out_path.parent.mkdir(parents=True, exist_ok=True)

    model_name = resolve_evaluator_model(args.model)
    old_by_file = _load_old_ratios(
        args.old_comparison.resolve() if args.old_comparison is not None else None
    )
    log_paths = _collect_logs(base_dir, overlay_dir)
    print(
        f"Evaluating {len(log_paths)} logs with atomic coverage "
        f"({model_name}, workers={args.workers}) ..."
    )
    print(f"base:    {base_dir}")
    if overlay_dir is not None:
        print(f"overlay: {overlay_dir}")
        print("note: old_ratio columns are historical; atomic_ratio uses overlayed current finals")

    results: list[dict[str, Any]] = []
    lock = threading.Lock()
    counter = [0]

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(_evaluate_one, log_path, model_name, old_by_file): log_path
            for log_path in log_paths
        }
        for future in as_completed(futures):
            row = future.result()
            with lock:
                counter[0] += 1
                print(
                    f"[{counter[0]:03d}/{len(log_paths)}] {row['topic']}/{row['file']} "
                    f"old={row['old_ratio']} atomic={row['atomic_ratio']} "
                    f"({row['atomic_covered']}/{row['atomic_total']})",
                    flush=True,
                )
            results.append(row)

    results.sort(key=lambda row: (row["topic"], row["file"]))
    summary = _aggregate(results)

    print()
    print("=" * 70)
    print("ATOMIC COVERAGE — SUMMARY BY METHOD")
    print("=" * 70)
    print(f"{'method':<14}{'n':>4}{'old_mean':>12}{'atomic_mean':>14}{'atomic_items':>15}")
    for method, agg in summary.items():
        print(
            f"{method:<14}{agg['n']:>4}{str(agg['old_coverage_mean']):>12}"
            f"{str(agg['atomic_coverage_mean']):>14}{str(agg['atomic_items_mean']):>15}"
        )

    out_path.write_text(
        json.dumps(
            {"summary_by_method": summary, "detail": results},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nSaved: {out_path}")

    header = "topic,category,method,old_ratio,atomic_ratio,atomic_covered,atomic_total\n"
    lines = [header]
    for row in results:
        lines.append(
            f"{row['topic']},{row['category']},{row['method']},{row['old_ratio']},"
            f"{row['atomic_ratio']},{row['atomic_covered']},{row['atomic_total']}\n"
        )
    csv_out_path.write_text("".join(lines), encoding="utf-8")
    print(f"Saved: {csv_out_path}")


if __name__ == "__main__":
    main()
