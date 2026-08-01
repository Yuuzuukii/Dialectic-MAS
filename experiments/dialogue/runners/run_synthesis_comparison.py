"""止揚統合の比較実験: 5トピック x max_dialogue_turns(10~20) x 5条件を実行する.

5条件:
  - mad_judge:      MAD議論 + ジャッジによる回答生成（勝者決め）。method="mad"。
  - mad_synthesis:  MAD議論 + 止揚による統合（共通統合プロンプト）。method="mad_synthesis"。
  - free_debate:    Free Debate議論 + 止揚による統合。method="free_debate"。
  - no_schema:      No Schema Argumentation Modelの議論 + 止揚による統合。method="no_schema"。
  - schema:         Schema Argumentation Modelの議論 + 止揚による統合。method="schema"。

比較軸は `max_dialogue_turns`（対話フェーズの発話数そのものの絶対上限、全手法共通）であり、
`max_turns`（ラウンド数上限）は十分大きい値に固定して max_dialogue_turns だけが効くようにする。
Schema/No Schemaの AG1/AG2 折半ロジックは撤廃済み（nodes.py 参照）。

ログは条件ごとに独立したディレクトリへ保存される（eval_sweep_rubrics.py に
そのまま --sweep で渡せる turns-first 構造）:
  <output_root>/mad_judge/turns{T:02d}_attempts01/<category>/<topic>/mad_*.json
  <output_root>/mad_synthesis/turns{T:02d}_attempts01/<category>/<topic>/mad_synthesis_*.json
  <output_root>/free_debate_synthesis/turns{T:02d}_attempts01/<category>/<topic>/free_debate_*.json
  <output_root>/no_schema_synthesis/turns{T:02d}_attempts01/<category>/<topic>/no_schema_*.json
  <output_root>/schema_synthesis/turns{T:02d}_attempts01/<category>/<topic>/schema_*.json
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from experiments.dialogue.common import (
        LOGS_DIR,
        all_topic_files,
        run_free_debate_topic_once,
        run_mad_topic_once,
        run_no_schema_topic_once,
        run_schema_topic_once,
    )
except ModuleNotFoundError:  # pragma: no cover - direct file execution.
    from common import (  # type: ignore
        LOGS_DIR,
        all_topic_files,
        run_free_debate_topic_once,
        run_mad_topic_once,
        run_no_schema_topic_once,
        run_schema_topic_once,
    )

CONDITIONS = ("mad_judge", "mad_synthesis", "free_debate", "no_schema", "schema")
# 各条件の出力先ディレクトリ名。条件ごとに独立した sweep ディレクトリ
# （<output_root>/<dir名>/turnsNN_attempts01/<category>/<topic>/{method}_*.json）
# にすることで、eval_sweep_rubrics.py にそのまま --sweep で渡せる（turns-first構造を維持）。
CONDITION_DIR_NAMES = {
    "mad_judge": "mad_judge",
    "mad_synthesis": "mad_synthesis",
    "free_debate": "free_debate_synthesis",
    "no_schema": "no_schema_synthesis",
    "schema": "schema_synthesis",
}
DEFAULT_TURN_VALUES = tuple(range(10, 21))
DEFAULT_MAX_TURNS = 20  # ラウンド上限。max_dialogue_turnsだけが効くよう十分大きくする。


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the synthesis-comparison sweep (5 conditions x N topics x turn budgets)."
    )
    parser.add_argument(
        "--limit", type=int, default=5, help="先頭から何トピック使うか（既定5）。"
    )
    parser.add_argument(
        "--offset",
        type=int,
        default=0,
        help="トピックの開始位置（--limitと併用。offset=5,limit=5で6〜10トピック目を追加実行する等）。",
    )
    parser.add_argument(
        "--turn-values",
        type=str,
        default=",".join(str(t) for t in DEFAULT_TURN_VALUES),
        help="max_dialogue_turnsの候補を','区切りで指定（既定: 10..20）。",
    )
    parser.add_argument(
        "--max-turns",
        type=int,
        default=DEFAULT_MAX_TURNS,
        help="ラウンド上限（max_dialogue_turnsだけが効くよう十分大きい値にする。既定20）。",
    )
    parser.add_argument(
        "--conditions",
        type=str,
        default=",".join(CONDITIONS),
        help=f"実行する条件を','区切りで指定（既定: 全5条件 = {','.join(CONDITIONS)}）。",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=None,
        help="ログの出力先ルート（既定: logs/sweep_synthesis_comparison_<timestamp>）。",
    )
    parser.add_argument(
        "--concurrency", type=int, default=20, help="同時実行数の上限（既定20）。"
    )
    parser.add_argument(
        "--fail-fast", action="store_true", help="最初の失敗で停止する。"
    )
    return parser.parse_args()


async def run_one(
    condition: str,
    topic_file: Path,
    turns: int,
    max_turns: int,
    combo_dir: Path,
) -> None:
    if condition == "mad_judge":
        await run_mad_topic_once(
            topic_file,
            max_turns=max_turns,
            max_dialogue_turns=turns,
            use_synthesis=False,
            output_root=combo_dir,
        )
    elif condition == "mad_synthesis":
        await run_mad_topic_once(
            topic_file,
            max_turns=max_turns,
            max_dialogue_turns=turns,
            use_synthesis=True,
            output_root=combo_dir,
        )
    elif condition == "free_debate":
        await run_free_debate_topic_once(
            topic_file,
            max_turns=max_turns,
            max_dialogue_turns=turns,
            output_root=combo_dir,
        )
    elif condition == "no_schema":
        await run_no_schema_topic_once(
            topic_file,
            max_turns=max_turns,
            max_dialogue_turns=turns,
            output_root=combo_dir,
        )
    elif condition == "schema":
        await run_schema_topic_once(
            topic_file,
            max_turns=max_turns,
            max_dialogue_turns=turns,
            output_root=combo_dir,
        )
    else:
        raise ValueError(f"Unknown condition: {condition}")


async def run_unit(
    condition: str,
    topic_file: Path,
    turns: int,
    max_turns: int,
    combo_dir: Path,
    semaphore: asyncio.Semaphore,
    fail_fast: bool,
) -> None:
    async with semaphore:
        try:
            await run_one(condition, topic_file, turns, max_turns, combo_dir)
        except Exception as exc:  # noqa: BLE001 - keep the sweep going
            print(
                f"[error] condition={condition} topic={topic_file.stem} turns={turns}: {exc}",
                file=sys.stderr,
                flush=True,
            )
            if fail_fast:
                raise


async def main() -> None:
    args = parse_args()
    started = datetime.now().strftime("%Y%m%d_%H%M%S")
    sweep_root = args.output_root or (LOGS_DIR / f"sweep_synthesis_comparison_{started}")

    files = all_topic_files()[args.offset : args.offset + args.limit]
    turn_values = [int(t.strip()) for t in args.turn_values.split(",") if t.strip()]
    conditions = [c.strip() for c in args.conditions.split(",") if c.strip()]
    for c in conditions:
        if c not in CONDITIONS:
            raise ValueError(f"Unknown condition: {c} (choices: {CONDITIONS})")

    total_units = len(files) * len(turn_values) * len(conditions)
    print(
        f"=== synthesis comparison: {len(files)} topics x {len(turn_values)} turn values "
        f"x {len(conditions)} conditions = {total_units} dialogue runs ===",
        flush=True,
    )
    print(f"topics: {[f.stem for f in files]}", flush=True)
    print(f"turn_values: {turn_values}", flush=True)
    print(f"conditions: {conditions}", flush=True)
    print(f"logs -> {sweep_root}", flush=True)
    print(f"concurrency = {args.concurrency}", flush=True)

    semaphore = asyncio.Semaphore(max(1, args.concurrency))
    tasks = []
    for turns in turn_values:
        for condition in conditions:
            combo_dir = (
                sweep_root / CONDITION_DIR_NAMES[condition] / f"turns{turns:02d}_attempts01"
            )
            for topic_file in files:
                tasks.append(
                    run_unit(
                        condition,
                        topic_file,
                        turns,
                        args.max_turns,
                        combo_dir,
                        semaphore,
                        args.fail_fast,
                    )
                )
    await asyncio.gather(*tasks)

    print(f"=== done. logs under {sweep_root} ===", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
