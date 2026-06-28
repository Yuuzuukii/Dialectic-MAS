"""Overnight sweep (free_debate 版): 1 topic x (protocol loop limit).

弁証法プロトコルを使わない自由討議ベースライン（docs/free_debate_protocol_plan.md）を、
schema/no_schemaと同じ`max_turns`（1, 5, 10）でsweepする。

main argument の再試行という概念が無いため、`max_main_argument_attempts`軸は存在しない。
ディレクトリ命名は`eval_sweep.py`の既存パターン（`turns(\\d+)_attempts\\d+`）と互換にするため、
`turns{T:02d}_attempts01`に固定する。

ログは
  logs/sweep/<topic_stem>_<開始時刻>/turns{T:02d}_attempts01/scenarios/<topic_stem>/free_debate_*.json
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
    from src.dialogue.common import LOGS_DIR, run_free_debate_topic_once
except ModuleNotFoundError:  # pragma: no cover - direct file execution.
    from common import LOGS_DIR, run_free_debate_topic_once  # type: ignore

# プロトコルのループ上限（max_turns）の候補。schema/no_schemaと同じ値を使う。
PROTOCOL_MAX_TURNS = (1, 5, 10)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sweep protocol loop limits for one topic (free_debate baseline, no protocol)."
    )
    parser.add_argument(
        "json_file",
        help="Path to a topic JSON file (e.g. datasets/scenarios/curry_logic.json).",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=1,
        help="Number of runs per max_turns combination.",
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
            "max_turns を ',' 区切りで列挙（例: '10'）。未指定なら全combos(1,5,10)を実行。"
        ),
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="同時に実行するcombo数の上限。1なら従来通り直列実行。",
    )
    return parser.parse_args()


def parse_only(only: str | None) -> list[int] | None:
    """'--only' 文字列を [max_turns, ...] に変換する."""
    if only is None:
        return None
    return [int(token.strip()) for token in only.split(",") if token.strip()]


async def run_combo(
    topic_file: Path,
    sweep_root: Path,
    max_turns: int,
    runs: int,
    index: int,
    total: int,
    semaphore: asyncio.Semaphore,
) -> None:
    combo_dir = sweep_root / f"turns{max_turns:02d}_attempts01"
    async with semaphore:
        print(f"[{index}/{total}] start max_turns={max_turns} -> {combo_dir}", flush=True)
        for run_index in range(1, runs + 1):
            try:
                await run_free_debate_topic_once(
                    topic_file,
                    max_turns=max_turns,
                    output_root=combo_dir,
                    run_index=run_index if runs > 1 else None,
                )
            except Exception as exc:  # noqa: BLE001 - keep the sweep going overnight
                print(
                    f"[error] turns={max_turns} run={run_index}: {exc}",
                    file=sys.stderr,
                    flush=True,
                )
        print(f"[{index}/{total}] done max_turns={max_turns}", flush=True)


async def main() -> None:
    args = parse_args()
    topic_file = Path(args.json_file)
    started = datetime.now().strftime("%Y%m%d_%H%M%S")
    sweep_root = args.output_root / f"{topic_file.stem}_{started}"

    combos = parse_only(args.only) or list(PROTOCOL_MAX_TURNS)
    total = len(combos)
    print(f"=== {topic_file.stem}: {total} combinations x {args.runs} runs ===", flush=True)
    print(f"logs -> {sweep_root}", flush=True)
    print(f"concurrency = {args.concurrency}", flush=True)

    semaphore = asyncio.Semaphore(max(1, args.concurrency))
    await asyncio.gather(
        *(
            run_combo(topic_file, sweep_root, max_turns, args.runs, i, total, semaphore)
            for i, max_turns in enumerate(combos, start=1)
        )
    )

    print(f"=== done. logs under {sweep_root} ===", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
