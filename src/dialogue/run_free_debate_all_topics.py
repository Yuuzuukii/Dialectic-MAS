"""Overnight sweep (free_debate 版、全トピック): datasets/ 配下の全トピック x
(protocol loop limit) を総当たりする。

main argument の再試行という概念が無いため、attempts 軸は存在しない。ディレクトリ命名は
eval_sweep.py の既存パターン（turns(\\d+)_attempts\\d+）と互換にするため、
turns{T:02d}_attempts01 に固定する。

ログは
  <output_root>/turns{T:02d}_attempts01/<category>/<topic>/free_debate_*.json
に保存される。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from src.dialogue.common import LOGS_DIR, all_topic_files, run_free_debate_topic_once
except ModuleNotFoundError:  # pragma: no cover - direct file execution.
    from common import LOGS_DIR, all_topic_files, run_free_debate_topic_once  # type: ignore

PROTOCOL_MAX_TURNS = (1, 5, 10)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sweep protocol loop limits over every topic under datasets/ (free_debate baseline)."
    )
    parser.add_argument(
        "--runs", type=int, default=1, help="Number of runs per (topic, max_turns) combination."
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=None,
        help="Root directory for sweep logs (default: logs/sweep_all_topics_free_debate_<timestamp>).",
    )
    parser.add_argument(
        "--only",
        type=str,
        default=None,
        help="未完了の組み合わせだけ再実行する場合に指定。max_turns を ',' 区切りで列挙（例: '10'）。",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="同時に実行する (topic, max_turns) 単位数の上限。1なら直列実行。",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="実行するトピック数の上限（10 なら先頭から10トピックだけ）。バッチ実行用。",
    )
    parser.add_argument(
        "--offset",
        type=int,
        default=0,
        help="トピックの開始位置（--limit と併用。offset=10,limit=10 で 11〜20 トピック目）。",
    )
    parser.add_argument(
        "--fail-fast", action="store_true", help="Stop on the first failure."
    )
    return parser.parse_args()


def parse_only(only: str | None) -> list[int] | None:
    if only is None:
        return None
    return [int(token.strip()) for token in only.split(",") if token.strip()]


async def run_unit(
    topic_file: Path,
    combo_dir: Path,
    max_turns: int,
    runs: int,
    semaphore: asyncio.Semaphore,
    fail_fast: bool,
) -> None:
    async with semaphore:
        for run_index in range(1, runs + 1):
            try:
                await run_free_debate_topic_once(
                    topic_file,
                    max_turns=max_turns,
                    output_root=combo_dir,
                    run_index=run_index if runs > 1 else None,
                )
            except Exception as exc:
                print(
                    f"[error] {topic_file} turns={max_turns} run={run_index}: {exc}",
                    file=sys.stderr,
                    flush=True,
                )
                if fail_fast:
                    raise


async def main() -> None:
    args = parse_args()
    started = datetime.now().strftime("%Y%m%d_%H%M%S")
    sweep_root = args.output_root or (LOGS_DIR / f"sweep_all_topics_free_debate_{started}")

    files = all_topic_files()
    if args.offset:
        files = files[args.offset :]
    if args.limit is not None:
        files = files[: args.limit]
    combos = parse_only(args.only) or list(PROTOCOL_MAX_TURNS)
    total_units = len(files) * len(combos)
    print(
        f"=== free_debate: {len(files)} topics x {len(combos)} combos x {args.runs} runs "
        f"= {total_units * args.runs} dialogue runs ===",
        flush=True,
    )
    print(f"logs -> {sweep_root}", flush=True)
    print(f"concurrency = {args.concurrency}", flush=True)

    semaphore = asyncio.Semaphore(max(1, args.concurrency))
    tasks = []
    for max_turns in combos:
        combo_dir = sweep_root / f"turns{max_turns:02d}_attempts01"
        for topic_file in files:
            tasks.append(run_unit(topic_file, combo_dir, max_turns, args.runs, semaphore, args.fail_fast))
    await asyncio.gather(*tasks)

    print(f"=== done. logs under {sweep_root} ===", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
