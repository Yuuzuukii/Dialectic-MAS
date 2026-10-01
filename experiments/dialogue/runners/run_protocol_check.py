"""トピック x 手法 x ターン数 x 回数 を（同時実行数を制限して）実行し、CLAUDE.md §11 の構成でログを保存する.

ログは
  logs/experiment_<日時>/turns<N>/raw_dialogue/<カテゴリ>/<トピック>/[NN_]<method>_<日時>.json
に保存される。可視化は続けて次を実行する:
  python -m experiments.eval.plots.plot_argument_network \
    logs/experiment_<日時>/turns<N>/raw_dialogue \
    -o logs/experiment_<日時>/turns<N>/eval_result/dialogue_tree/argument_network.html

Usage:
    python -m experiments.dialogue.runners.run_protocol_check \
      datasets/Education/animal_dissection.json --methods schema --turns 20
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.dialogue.common import (
    LOGS_DIR,
    run_free_debate_topic_once,
    run_mad_topic_once,
    run_no_schema_topic_once,
    run_schema_topic_once,
)

RUNNERS: dict[str, Callable[..., Awaitable[Path]]] = {
    "schema": run_schema_topic_once,
    "no_schema": run_no_schema_topic_once,
    "free_debate": run_free_debate_topic_once,
    "mad": run_mad_topic_once,
}
# ラウンド上限は十分大きくして、max_dialogue_turns だけが効くようにする。
DEFAULT_MAX_TURNS = 40


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "topic_files", nargs="+", help="トピック JSON（複数可。例: datasets/Education/animal_dissection.json）"
    )
    parser.add_argument("--methods", default="schema,no_schema", help="',' 区切り（schema / no_schema / free_debate / mad）。")
    parser.add_argument("--turns", default="20", help="max_dialogue_turns を ',' 区切りで（例: 10,20,30）。")
    parser.add_argument("--runs", type=int, default=1, help="各条件の実行回数。")
    parser.add_argument("--max-turns", type=int, default=DEFAULT_MAX_TURNS, help="ラウンド上限。")
    parser.add_argument(
        "--experiment-dir",
        type=Path,
        default=None,
        help="既存の実験フォルダ（logs/experiment_<日時>）に追加で保存する。未指定なら新しく作る。",
    )
    parser.add_argument("--concurrency", type=int, default=8, help="同時に実行する run 数の上限（API のレート制限対策）。")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    methods = [m.strip() for m in args.methods.split(",") if m.strip()]
    turns_list = [int(t) for t in args.turns.split(",") if t.strip()]
    root = args.experiment_dir or LOGS_DIR / f"experiment_{datetime.now():%Y%m%d_%H%M%S}"
    print(f"logs -> {root}", flush=True)

    semaphore = asyncio.Semaphore(max(1, args.concurrency))

    async def limited(coro_fn: Callable[..., Awaitable[Path]], **kwargs: Any) -> Path:
        async with semaphore:
            return await coro_fn(**kwargs)

    jobs = [
        limited(
            RUNNERS[method],
            topic_file=topic_file,
            max_turns=args.max_turns,
            max_dialogue_turns=turns,
            output_root=root / f"turns{turns}" / "raw_dialogue",
            run_index=index,
        )
        for turns in turns_list
        for topic_file in args.topic_files
        for method in methods
        for index in range(1, args.runs + 1)
    ]
    print(f"=== {len(jobs)} runs（同時 {args.concurrency}）===", flush=True)
    results = await asyncio.gather(*jobs, return_exceptions=True)
    for result in results:
        print("ERROR" if isinstance(result, Exception) else "saved", result, flush=True)


if __name__ == "__main__":
    asyncio.run(main())
