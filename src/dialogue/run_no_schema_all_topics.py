"""Overnight sweep (no_schema 版、全トピック): datasets/ 配下の全トピック x
(protocol loop limit) x (main argument loop limit) を総当たりする。

run_schema_all_topics.py の no_schema 版。ログは
  <output_root>/turns{T:02d}_attempts{A:02d}/<category>/<topic>/no_schema_*.json
に保存される（eval_sweep.py の集計フォーマットと互換）。
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
    from src.dialogue.common import LOGS_DIR, all_topic_files, run_no_schema_topic_once
except ModuleNotFoundError:  # pragma: no cover - direct file execution.
    from common import LOGS_DIR, all_topic_files, run_no_schema_topic_once  # type: ignore

PROTOCOL_MAX_TURNS = (1, 5, 10)
MAIN_ARGUMENT_MAX_ATTEMPTS = range(1, 11)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sweep protocol/main-argument loop limits over every topic under datasets/ (no_schema)."
    )
    parser.add_argument(
        "--runs", type=int, default=1, help="Number of runs per (topic, max_turns, max_attempts) combination."
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=None,
        help="Root directory for sweep logs (default: logs/sweep_all_topics_no_schema_<timestamp>).",
    )
    parser.add_argument(
        "--turns",
        type=str,
        default=None,
        help=(
            "実行する max_turns（プロトコルのループ上限）だけを ',' 区切りで指定"
            "（例: '1' でプロトコル1のみ、attempts(1-10)は全て実行）。未指定なら(1,5,10)全て。"
        ),
    )
    parser.add_argument(
        "--only",
        type=str,
        default=None,
        help=(
            "未完了の組み合わせだけ再実行する場合に指定。"
            "'max_turns:max_attempts' を ',' 区切りで列挙（例: '10:8,10:9,10:10'）。"
            "--turns より優先される。未指定なら全combos(3x10)を実行。"
        ),
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="同時に実行する (topic, combo) 単位数の上限。1なら直列実行。",
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


def parse_only(only: str | None) -> list[tuple[int, int]] | None:
    if only is None:
        return None
    combos: list[tuple[int, int]] = []
    for token in only.split(","):
        token = token.strip()
        if not token:
            continue
        turns_str, attempts_str = token.split(":")
        combos.append((int(turns_str), int(attempts_str)))
    return combos


async def run_unit(
    topic_file: Path,
    combo_dir: Path,
    max_turns: int,
    max_attempts: int,
    runs: int,
    semaphore: asyncio.Semaphore,
    fail_fast: bool,
) -> None:
    async with semaphore:
        for run_index in range(1, runs + 1):
            try:
                await run_no_schema_topic_once(
                    topic_file,
                    max_turns=max_turns,
                    max_attack_attempts=max_attempts,
                    output_root=combo_dir,
                    run_index=run_index if runs > 1 else None,
                )
            except Exception as exc:
                print(
                    f"[error] {topic_file} turns={max_turns} attempts={max_attempts} run={run_index}: {exc}",
                    file=sys.stderr,
                    flush=True,
                )
                if fail_fast:
                    raise


async def main() -> None:
    args = parse_args()
    started = datetime.now().strftime("%Y%m%d_%H%M%S")
    sweep_root = args.output_root or (LOGS_DIR / f"sweep_all_topics_no_schema_{started}")

    files = all_topic_files()
    if args.offset:
        files = files[args.offset :]
    if args.limit is not None:
        files = files[: args.limit]
    turns_filter = (
        [int(t.strip()) for t in args.turns.split(",") if t.strip()] if args.turns else PROTOCOL_MAX_TURNS
    )
    combos = parse_only(args.only) or [
        (max_turns, max_attempts)
        for max_turns in turns_filter
        for max_attempts in MAIN_ARGUMENT_MAX_ATTEMPTS
    ]
    total_units = len(files) * len(combos)
    print(
        f"=== no_schema: {len(files)} topics x {len(combos)} combos x {args.runs} runs "
        f"= {total_units * args.runs} dialogue runs ===",
        flush=True,
    )
    print(f"logs -> {sweep_root}", flush=True)
    print(f"concurrency = {args.concurrency}", flush=True)

    semaphore = asyncio.Semaphore(max(1, args.concurrency))
    tasks = []
    for max_turns, max_attempts in combos:
        combo_dir = sweep_root / f"turns{max_turns:02d}_attempts{max_attempts:02d}"
        for topic_file in files:
            tasks.append(
                run_unit(
                    topic_file,
                    combo_dir,
                    max_turns,
                    max_attempts,
                    args.runs,
                    semaphore,
                    args.fail_fast,
                )
            )
    await asyncio.gather(*tasks)

    print(f"=== done. logs under {sweep_root} ===", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
