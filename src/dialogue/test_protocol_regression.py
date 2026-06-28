"""ワークフロー修正時の正当性回帰テスト.

curry_logic / camera_logic は、両エージェントのstance（事実とルール）を正しく統合すれば
客観的に答えが一意に決まる論理パズル（どちらも正解は "c"）。schema協議を並列に複数回実行し、
最終回答が正解(c)に到達した割合を表示する。ワークフロー（workflow.py/nodes.py/edges.py/
argumentation_model.py/prompts.py）を修正した際の回帰テストとして使う想定。

Usage:
    python src/dialogue/test_protocol_regression.py
    python src/dialogue/test_protocol_regression.py --runs 10 --max-turns 1
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from src.dialogue.common import DATASETS_DIR, LOGS_DIR, run_schema_topic_once
except ModuleNotFoundError:  # pragma: no cover - direct file execution.
    from common import DATASETS_DIR, LOGS_DIR, run_schema_topic_once  # type: ignore

# (短縮ラベル, topic file, 正解の選択肢)。どちらも両者のstanceを正しく統合すると
# "c" が唯一拒否されない選択肢になる。
SCENARIOS: list[tuple[str, str, str]] = [
    ("curry", "scenarios/curry_logic.json", "c"),
    ("camera", "scenarios/camera_logic.json", "c"),
]

_ANSWER_RE_TEMPLATE = r"\b{}\b"


def _mentions_answer(final_answer: str | None, expected: str) -> bool:
    """final_answer のテキストに、正解の選択肢(例: "c")が単語境界で出現するか判定する."""
    if not final_answer:
        return False
    return re.search(_ANSWER_RE_TEMPLATE.format(re.escape(expected)), final_answer, re.IGNORECASE) is not None


def _summarize_dialogue(dialogue_history: list[dict[str, Any]], max_chars: int = 120) -> str:
    """1 run の dialogue_history を1行ずつの短い要約にする."""
    lines = []
    for i, record in enumerate(dialogue_history, start=1):
        agent = record.get("agent", "?")
        argument = record.get("argument")
        text = json.dumps(argument, ensure_ascii=False) if isinstance(argument, dict) else str(argument or "")
        text = text.replace("\n", " ").strip()
        if len(text) > max_chars:
            text = text[: max_chars - 1] + "…"
        lines.append(f"    [{i}] {agent}: {text}")
    return "\n".join(lines) if lines else "    (no dialogue)"


async def _run_one(topic_file: Path, max_turns: int, output_root: Path, run_index: int) -> dict[str, Any]:
    path = await run_schema_topic_once(
        topic_file,
        max_turns=max_turns,
        output_root=output_root,
        run_index=run_index,
    )
    log = json.loads(path.read_text(encoding="utf-8"))
    return {"path": path, "log": log}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="curry_logic/camera_logic を並列に複数回実行し、正解(c)到達率を表示する回帰テスト。"
    )
    parser.add_argument("--runs", type=int, default=10, help="シナリオごとの実行回数。")
    parser.add_argument("--max-turns", type=int, default=1, help="議論ラウンド数の上限。")
    parser.add_argument(
        "--output-root", type=Path, default=LOGS_DIR / "protocol_regression", help="ログ出力先ルート。"
    )
    parser.add_argument(
        "--quiet", action="store_true", help="各runの対話要約を省略し、pass/fail件数だけ表示する。"
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    summary_parts: list[str] = []

    for label, topic, expected in SCENARIOS:
        topic_file = DATASETS_DIR / topic
        results = await asyncio.gather(
            *(
                _run_one(topic_file, args.max_turns, args.output_root, index)
                for index in range(1, args.runs + 1)
            ),
            return_exceptions=True,
        )

        passed = 0
        print(f"=== [{topic_file.stem}] {args.runs} runs (expected answer: {expected}) ===", flush=True)
        for index, result in enumerate(results, start=1):
            if isinstance(result, BaseException):
                print(f"--- run {index}/{args.runs}: ERROR: {result} ---", flush=True)
                continue
            log = result["log"]
            final_answer = log.get("final_answer")
            ok = _mentions_answer(final_answer, expected)
            passed += int(ok)
            status = "PASS" if ok else "FAIL"
            print(f"--- run {index}/{args.runs}: {status} ---", flush=True)
            if not args.quiet:
                print(_summarize_dialogue(log.get("dialogue_history", [])), flush=True)
                print(f"    final_answer: {(final_answer or '(none)').replace(chr(10), ' ')[:200]}", flush=True)

        summary_parts.append(f"{label}({passed}/{args.runs})")
        print(flush=True)

    print("=== SUMMARY ===", flush=True)
    print(", ".join(summary_parts), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
