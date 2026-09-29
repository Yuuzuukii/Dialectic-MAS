"""Run first-person SVI evaluation over debate logs.

Supports an optional overlay directory so unchanged baselines can be read from the
original log root while re-finalized schema/no_schema logs replace matching files.

Examples:
    python -m experiments.eval.runners.eval_svi_final --trials 5 --workers 8
    python -m experiments.eval.runners.eval_svi_final \
      --base-dir logs/final_gpt54nano_turns10 \
      --overlay-dir logs/final_gpt54nano_turns10_two_path \
      --out logs/final_gpt54nano_turns10_two_path/svi_comparison.json \
      --trials 5 --workers 8
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

DEFAULT_BASE_DIR = ROOT / "logs" / "final_gpt54nano_turns10"
DEFAULT_OUT = DEFAULT_BASE_DIR / "svi_comparison.json"
_FILENAME_RE = re.compile(r"^\d+_(?P<method>.+)_\d{8}_\d{6}_\d+$")


def _relative_log_map(root: Path) -> dict[Path, Path]:
    return {
        path.relative_to(root): path
        for path in sorted(root.glob("*/*/*.json"))
        if _FILENAME_RE.match(path.stem)
    }


def _collect_logs(
    base_dir: Path,
    overlay_dir: Path | None,
    trials_per_method: int,
) -> list[Path]:
    merged = _relative_log_map(base_dir)
    if overlay_dir is not None:
        if not overlay_dir.exists():
            raise FileNotFoundError(f"Overlay directory does not exist: {overlay_dir}")
        merged.update(_relative_log_map(overlay_dir))

    by_group: dict[tuple[str, str], list[Path]] = {}
    for relative_path, path in sorted(merged.items()):
        match = _FILENAME_RE.match(path.stem)
        if match is None:
            continue
        method = match.group("method")
        topic = relative_path.parent.name
        by_group.setdefault((topic, method), []).append(path)

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
    """CLI entrypoint."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=None)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument(
        "--trials",
        type=int,
        default=1,
        help="method x topic の組ごとに使う試行数（デフォルト1）",
    )
    parser.add_argument(
        "--base-dir",
        type=Path,
        default=DEFAULT_BASE_DIR,
        help="Base log root. Unchanged methods are read from here.",
    )
    parser.add_argument(
        "--overlay-dir",
        type=Path,
        default=None,
        help=(
            "Optional log root whose matching relative paths replace base logs. "
            "Use this for two-path schema/no_schema outputs."
        ),
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output JSON path. Default: overlay-dir/svi_comparison.json when overlay is set, else base-dir/svi_comparison.json.",
    )
    args = parser.parse_args()

    base_dir = args.base_dir.resolve()
    overlay_dir = args.overlay_dir.resolve() if args.overlay_dir is not None else None
    out_path = (
        args.out.resolve()
        if args.out is not None
        else (overlay_dir / "svi_comparison.json" if overlay_dir is not None else base_dir / "svi_comparison.json")
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)

    model_name = resolve_evaluator_model(args.model)
    log_paths = _collect_logs(base_dir, overlay_dir, args.trials)
    print(
        f"Evaluating {len(log_paths)} logs with SVI "
        f"({model_name}, workers={args.workers}) ..."
    )
    print(f"base:    {base_dir}")
    if overlay_dir is not None:
        print(f"overlay: {overlay_dir}")

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
    out_path.write_text(
        json.dumps({"detail": results}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Saved: {out_path}")


if __name__ == "__main__":
    main()
