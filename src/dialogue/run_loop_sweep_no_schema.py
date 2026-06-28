"""Overnight sweep (no_schema 版): 1 topic x (protocol loop limit) x (main argument loop limit).

ある1つのトピックに対して、以下の組み合わせ（3 x 10 = 30 通り）をそれぞれ実行する。

- プロトコルのループ上限（debate round の上限 = State.max_turns）: 1, 5, 10
- 主張のループ上限（1ラウンド・1 proponent あたりの main argument 試行回数の上限
  = State.max_main_argument_attempts）: 1〜10

schema 版（run_loop_sweep.py）と同じプロトコルを使い、State.output_mode のみ
"no_schema" にして自由記述形式の出力を生成する。

ログは
  logs/sweep/<topic_stem>_<開始時刻>/turns{T:02d}_attempts{A:02d}/scenarios/<topic_stem>/no_schema_*.json
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
    from src.dialogue.common import LOGS_DIR, run_no_schema_topic_once
except ModuleNotFoundError:  # pragma: no cover - direct file execution.
    from common import LOGS_DIR, run_no_schema_topic_once  # type: ignore

# プロトコルのループ上限（State.max_turns）の候補。
PROTOCOL_MAX_TURNS = (1, 5, 10)
# 主張のループ上限（State.max_main_argument_attempts）の候補。
MAIN_ARGUMENT_MAX_ATTEMPTS = range(1, 11)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sweep protocol/main-argument loop limits for one topic (no_schema)."
    )
    parser.add_argument(
        "json_file",
        help="Path to a topic JSON file (e.g. datasets/scenarios/curry_logic.json).",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=1,
        help="Number of runs per (max_turns, max_attempts) combination.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=LOGS_DIR / "sweep",
        help="Root directory for sweep logs.",
    )
    parser.add_argument(
        "--only",
        type=str,
        default=None,
        help=(
            "未完了の組み合わせだけ再実行する場合に指定。"
            "'max_turns:max_attempts' を ',' 区切りで列挙（例: '10:6,10:7'）。"
            "未指定なら全combos(3x10)を実行。"
        ),
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="同時に実行するcombo数の上限。1なら従来通り直列実行。",
    )
    return parser.parse_args()


def parse_only(only: str | None) -> list[tuple[int, int]] | None:
    """'--only' 文字列を [(max_turns, max_attempts), ...] に変換する."""
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


async def run_combo(
    topic_file: Path,
    sweep_root: Path,
    max_turns: int,
    max_attempts: int,
    runs: int,
    index: int,
    total: int,
    semaphore: asyncio.Semaphore,
) -> None:
    combo_dir = sweep_root / f"turns{max_turns:02d}_attempts{max_attempts:02d}"
    async with semaphore:
        print(
            f"[{index}/{total}] start max_turns={max_turns} max_main_argument_attempts={max_attempts} "
            f"-> {combo_dir}",
            flush=True,
        )
        for run_index in range(1, runs + 1):
            try:
                await run_no_schema_topic_once(
                    topic_file,
                    max_turns=max_turns,
                    max_main_argument_attempts=max_attempts,
                    output_root=combo_dir,
                    run_index=run_index if runs > 1 else None,
                )
            except Exception as exc:  # noqa: BLE001 - keep the sweep going overnight
                print(
                    f"[error] turns={max_turns} attempts={max_attempts} run={run_index}: {exc}",
                    file=sys.stderr,
                    flush=True,
                )
        print(f"[{index}/{total}] done max_turns={max_turns} max_main_argument_attempts={max_attempts}", flush=True)


async def main() -> None:
    args = parse_args()
    topic_file = Path(args.json_file)
    started = datetime.now().strftime("%Y%m%d_%H%M%S")
    sweep_root = args.output_root / f"{topic_file.stem}_{started}"

    combos = parse_only(args.only) or [
        (max_turns, max_attempts)
        for max_turns in PROTOCOL_MAX_TURNS
        for max_attempts in MAIN_ARGUMENT_MAX_ATTEMPTS
    ]
    total = len(combos)
    print(f"=== {topic_file.stem}: {total} combinations x {args.runs} runs ===", flush=True)
    print(f"logs -> {sweep_root}", flush=True)
    print(f"concurrency = {args.concurrency}", flush=True)

    semaphore = asyncio.Semaphore(max(1, args.concurrency))
    await asyncio.gather(
        *(
            run_combo(topic_file, sweep_root, max_turns, max_attempts, args.runs, i, total, semaphore)
            for i, (max_turns, max_attempts) in enumerate(combos, start=1)
        )
    )

    print(f"=== done. logs under {sweep_root} ===", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
