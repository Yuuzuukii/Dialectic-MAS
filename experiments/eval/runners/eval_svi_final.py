"""Run first-person SVI evaluation over existing debate logs.

This module only defines the runner. It does not execute on import.
The official 16 SVI items are embedded in evaluation_svi.py for this non-commercial
research use, so no external questionnaire file is required.

Usage (when ready to run):
    python -m experiments.eval.runners.eval_svi_final
    python -m experiments.eval.runners.eval_svi_final --workers 8
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
from experiments.eval.scoring.evaluation_svi import evaluate_svi

LOGS_DIR = ROOT / "logs" / "final_gpt54nano_turns10"
OUT_PATH = LOGS_DIR / "svi_comparison.json"

_FILENAME_RE = re.compile(r"^\d+_(?P<method>.+)_\d{8}_\d{6}_\d+$")


def _collect_logs(trials_per_method: int) -> list[Path]:
    all_paths = sorted(LOGS_DIR.glob("*/*/*.json"))
    by_group: dict[tuple[str, str], list[Path]] = {}
    for path in all_paths:
        match = _FILENAME_RE.match(path.stem)
        method = match.group("method") if match else path.stem
        by_group.setdefault((path.parent.name, method), []).append(path)

    selected: list[Path] = []
    for group_paths in by_group.values():
        selected.extend(sorted(group_paths)[:trials_per_method])
    return sorted(selected)


def _evaluate_one(log_path: Path, model_name: str) -> dict[str, Any]:
    log = json.loads(log_path.read_text(encoding="utf-8"))
    judge_model = ChatOpenAI(model=model_name)
    result = evaluate_svi(log, judge_model)
    return {
        "file": log_path.name,
        "topic": log_path.parent.name,
        "category": log_path.parent.parent.name,
        "method": log.get("method") or log.get("mode"),
        "agent1": result["agent1"],
        "agent2": result["agent2"],
        "agent1_scores": result["agent1_scores"],
        "agent2_scores": result["agent2_scores"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=None)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument(
        "--trials",
        type=int,
        default=1,
        help="method x topic の組ごとに使う試行数（デフォルト1）",
    )
    args = parser.parse_args()

    model_name = resolve_evaluator_model(args.model)
    log_paths = _collect_logs(args.trials)
    print(
        f"Evaluating {len(log_paths)} logs with SVI "
        f"({model_name}, workers={args.workers}) ..."
    )

    results: list[dict[str, Any]] = []
    lock = threading.Lock()
    counter = [0]

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(_evaluate_one, log_path, model_name): log_path
            for log_path in log_paths
        }
        for future in as_completed(futures):
            result = future.result()
            with lock:
                counter[0] += 1
                print(
                    f"[{counter[0]:03d}/{len(log_paths)}] "
                    f"{result['topic']}/{result['file']}",
                    flush=True,
                )
            results.append(result)

    results.sort(key=lambda row: (row["topic"], row["file"]))
    OUT_PATH.write_text(
        json.dumps({"detail": results}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Saved: {OUT_PATH}")


if __name__ == "__main__":
    main()
