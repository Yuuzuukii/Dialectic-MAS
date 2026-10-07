"""既存の議論ログの最終回答だけを、旧 free_debate / MAD+止揚と同じ方式で作り直し、新しい実験フォルダに保存する.

方式（free_debate の旧実装と同じ）:
  1. AG1 と AG2 の「最後の発言」だけから、共通の統合プロンプトで統合ルールを 1 個作る。
  2. その統合ルールと議論全体の記録を渡して、最終回答を作る（決着なし用の共通プロンプト）。

議論の過程（dialogue_history・立場文・metrics など）はそのままコピーし、最終回答だけを作り直す。
元のログは書き換えない。決着した主張がある（consensus_reached が true の）ログは、最終回答を変えずにコピーする。

出力は ``<出力先>/turns<N>/raw_dialogue/<カテゴリ>/<トピック>/<元のファイル名>``。出力先を省略すると
``logs/experiment_<日時>/`` になる。

Usage:
    python -m experiments.dialogue.runners.refinalize_last_statements \
      --source logs/fin --methods schema [--dry-run] [--limit 3]
"""

# ruff: noqa: T201

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from src.agent.arguments import generate_final_answer, generate_integration  # noqa: E402
from src.agent.dialogue_transcript import render_argument_text  # noqa: E402
from src.agent.nodes import extract_integrated_rule  # noqa: E402

LOGS_DIR = ROOT / "logs"
FINALIZATION_PATH = "last_statements_rule"


def last_statement_by(history: list[dict[str, Any]], agent: str) -> str:
    """その話者の最後の発言を、読める文章にして返す."""
    for turn in reversed(history):
        if turn.get("agent") == agent:
            return render_argument_text(turn.get("argument"))
    return ""


async def integrate_last_statements(log: dict[str, Any]) -> str | None:
    """両者の最後の発言から、統合ルールを 1 個作る."""
    history = list(log.get("dialogue_history") or [])
    warrant_result = json.dumps(
        {
            "Argument1": {"agent": "AG1", "warrant": last_statement_by(history, "AG1")},
            "Argument2": {"agent": "AG2", "warrant": last_statement_by(history, "AG2")},
        },
        ensure_ascii=False,
    )
    state = SimpleNamespace(
        warrant_result=warrant_result,
        agent1_stance=log.get("agent1_stance", ""),
        agent2_stance=log.get("agent2_stance", ""),
        output_mode="no_schema",
    )
    output = await generate_integration(state)
    response = json.dumps(output.model_dump(exclude_none=True), ensure_ascii=False, indent=2)
    return extract_integrated_rule(response)


async def refinalize(log: dict[str, Any]) -> dict[str, Any]:
    """1 つのログの最終回答を、最後の発言の統合ルール方式で作り直す."""
    if log.get("consensus_reached") is True:
        copied = dict(log)
        copied["finalization_path"] = log.get("finalization_path") or "justified_argument"
        return copied
    history = list(log.get("dialogue_history") or [])
    rule = await integrate_last_statements(log)
    last_argument = history[-1].get("argument") if history else None
    if isinstance(last_argument, dict):
        last_argument = json.dumps(last_argument, ensure_ascii=False)
    state = SimpleNamespace(
        justified_argument=last_argument,
        dialogue_history=history,
        integrated_rules=[rule] if rule else [],
        consensus_reached=False,
        question=log.get("question", ""),
        agent1_stance=log.get("agent1_stance", ""),
        agent2_stance=log.get("agent2_stance", ""),
    )
    answer = await generate_final_answer(state)
    copied = dict(log)
    copied["previous_final_answer"] = log.get("final_answer")
    copied["last_statements_rule"] = rule
    copied["final_answer"] = answer.strip()
    copied["finalization_path"] = FINALIZATION_PATH
    return copied


def collect(source: Path, methods: frozenset[str]) -> list[tuple[Path, Path]]:
    """``(元のログ, 実験フォルダからの相対パス)`` を返す。手法はログの method で判定する."""
    found: list[tuple[Path, Path]] = []
    for path in sorted(source.glob("turns*/raw_dialogue/*/*/*.json")):
        if json.loads(path.read_text(encoding="utf-8")).get("method") in methods:
            found.append((path, path.relative_to(source)))
    return found


async def process_one(
    path: Path, relative: Path, *, output_root: Path, semaphore: asyncio.Semaphore
) -> tuple[str, str]:
    async with semaphore:
        log = await refinalize(json.loads(path.read_text(encoding="utf-8")))
        log["refinalized_from"] = str(path.resolve())
        out = output_root / relative
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return str(log.get("method")), str(log["finalization_path"])


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", type=Path, required=True, help="作り直す対象の実験フォルダ（例: logs/fin）。")
    parser.add_argument("--methods", default="schema", help="対象の手法を ',' 区切りで（既定: schema）。")
    parser.add_argument("--output-root", type=Path, default=None, help="既定は logs/experiment_<日時>/。")
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--limit", type=int, default=None, help="試運転用: 処理するログ数の上限。")
    parser.add_argument("--dry-run", action="store_true", help="LLM を呼ばず、対象の件数だけ表示する。")
    args = parser.parse_args()

    methods = frozenset(m.strip() for m in args.methods.split(",") if m.strip())
    jobs = collect(args.source, methods)
    if args.limit is not None:
        jobs = jobs[: args.limit]
    if not jobs:
        raise SystemExit("対象のログが見つかりません。")
    output_root = args.output_root or LOGS_DIR / f"experiment_{datetime.now():%Y%m%d_%H%M%S}"
    print(f"output: {output_root}")
    print(f"logs: {len(jobs)}（{', '.join(sorted(methods))}）", flush=True)
    if args.dry_run:
        return

    semaphore = asyncio.Semaphore(max(1, args.concurrency))
    results = await asyncio.gather(
        *[process_one(p, r, output_root=output_root, semaphore=semaphore) for p, r in jobs]
    )
    counts: dict[tuple[str, str], int] = {}
    for key in results:
        counts[key] = counts.get(key, 0) + 1
    for (method, path_name), value in sorted(counts.items()):
        print(f"  {method} / {path_name}: {value}")
    print(f"saved -> {output_root}")


if __name__ == "__main__":
    asyncio.run(main())
