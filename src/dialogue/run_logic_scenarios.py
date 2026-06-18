"""Run the schema-based dialogue for curry_logic / camera_logic, N times each.

正当性検証用に datasets/scenarios/curry_logic.json と camera_logic.json を
それぞれ指定回数（既定 10 回）実行し、logs/scenarios/<topic>/ にログを保存する。
"""

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from src.dialogue.common import DATASETS_DIR, LOGS_DIR, run_schema_topic_once
except ModuleNotFoundError:  # pragma: no cover - direct file execution.
    from common import DATASETS_DIR, LOGS_DIR, run_schema_topic_once  # type: ignore

TOPICS = ["scenarios/curry_logic.json", "scenarios/camera_logic.json"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run curry_logic and camera_logic scenarios N times each (schema method)."
    )
    parser.add_argument("--runs", type=int, default=10, help="Number of runs per topic.")
    parser.add_argument("--max-turns", type=int, default=1, help="Maximum debate rounds.")
    parser.add_argument("--output-root", type=Path, default=LOGS_DIR, help="Root directory for logs.")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    for topic in TOPICS:
        topic_file = DATASETS_DIR / topic
        print(f"=== [{topic_file.stem}] {args.runs} runs ===", flush=True)
        for index in range(1, args.runs + 1):
            print(f"--- run {index}/{args.runs} ---", flush=True)
            try:
                await run_schema_topic_once(
                    topic_file,
                    max_turns=args.max_turns,
                    output_root=args.output_root,
                    run_index=index,
                )
            except Exception as exc:  # noqa: BLE001 - continue with remaining runs
                print(f"[error] {topic_file} run {index}: {exc}", file=sys.stderr, flush=True)


if __name__ == "__main__":
    asyncio.run(main())
