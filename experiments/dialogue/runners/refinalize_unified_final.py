"""既存の議論ログの最終回答だけを、共通の作り方（src/agent/final_answer.py）で作り直す.

議論の過程（dialogue_history・立場文・metrics など）はそのままコピーし、最終回答だけを作り直す。
元のログは書き換えない。

作り方（schema / no_schema / free_debate / mad で共通）:
  - justified の主張があるログ: その論証と議論全体から最終回答を作る（統合案は作らない）。
  - ないログ: 各陣営の最後の主張から統合案を作り、統合案と議論全体から作る。
    schema / no_schema は最後の main、free_debate / mad は最後の発言を使う。
  - どちらかの陣営に主張がなければ: 統合案は作らず、議論全体だけから作る。

mad のログは、judge で作った元の版を残したまま、止揚の版を別ファイル（method=mad_synthesis）として
出す（元の mad のログは出力に含めない）。

出力は ``<出力先>/turns<N>/raw_dialogue/<カテゴリ>/<トピック>/<ファイル名>``。出力先を省略すると
``logs/experiment_<日時>/`` になる。

Usage:
    python -m experiments.dialogue.runners.refinalize_unified_final \
      --source logs/fin --methods free_debate,mad [--dry-run] [--limit 3]
"""

# ruff: noqa: T201

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from src.agent.final_answer import finalize  # noqa: E402

LOGS_DIR = ROOT / "logs"


def justified_argument_of(log: dict[str, Any]) -> str | None:
    """justified で決着した主張の本文を返す（なければ None）."""
    if log.get("consensus_reached") is not True:
        return None
    for turn in log.get("dialogue_history") or []:
        if turn.get("status") == "justified":
            argument = turn.get("argument")
            return (
                argument
                if isinstance(argument, str)
                else json.dumps(argument, ensure_ascii=False)
            )
    value = log.get("justified_argument")
    return value if isinstance(value, str) and value.strip() else None


async def refinalize(log: dict[str, Any]) -> dict[str, Any]:
    """1 つのログの最終回答を、共通の作り方で作り直す."""
    result = await finalize(
        question=str(log.get("question", "")),
        agent1_stance=str(log.get("agent1_stance", "")),
        agent2_stance=str(log.get("agent2_stance", "")),
        dialogue_history=list(log.get("dialogue_history") or []),
        justified_argument=justified_argument_of(log),
    )
    copied = dict(log)
    copied["previous_final_answer"] = log.get("final_answer")
    copied["final_answer"] = result["final_answer"]
    copied["integrated_proposal"] = result["integrated_proposal"]
    copied["finalization_path"] = result["finalization_path"]
    if log.get("method") == "mad":
        copied["method"] = "mad_synthesis"
    return copied


def collect(source: Path, methods: frozenset[str]) -> list[tuple[Path, Path]]:
    """``(元のログ, 実験フォルダからの相対パス)`` を返す。手法はログの method で判定する."""
    found: list[tuple[Path, Path]] = []
    for path in sorted(source.glob("turns*/raw_dialogue/*/*/*.json")):
        if json.loads(path.read_text(encoding="utf-8")).get("method") in methods:
            found.append((path, path.relative_to(source)))
    return found


def output_relative(relative: Path, method: str) -> Path:
    """mad のログは、ファイル名の手法名も mad_synthesis に置き換える."""
    if method != "mad":
        return relative
    return relative.with_name(
        re.sub(r"(^|_)mad_", r"\1mad_synthesis_", relative.name, count=1)
    )


async def process_one(
    path: Path, relative: Path, *, output_root: Path, semaphore: asyncio.Semaphore
) -> tuple[str, str]:
    async with semaphore:
        original = json.loads(path.read_text(encoding="utf-8"))
        log = await refinalize(original)
        log["refinalized_from"] = str(path.resolve())
        out = output_root / output_relative(relative, str(original.get("method")))
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return str(log.get("method")), str(log["finalization_path"])


async def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--source",
        type=Path,
        required=True,
        help="作り直す対象の実験フォルダ（例: logs/fin）。",
    )
    parser.add_argument(
        "--methods",
        default="schema,no_schema,free_debate",
        help="対象の手法を ',' 区切りで。",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=None,
        help="既定は logs/experiment_<日時>/。",
    )
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument(
        "--limit", type=int, default=None, help="試運転用: 処理するログ数の上限。"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="LLM を呼ばず、対象の件数だけ表示する。"
    )
    args = parser.parse_args()

    methods = frozenset(m.strip() for m in args.methods.split(",") if m.strip())
    jobs = collect(args.source, methods)
    if args.limit is not None:
        jobs = jobs[: args.limit]
    if not jobs:
        raise SystemExit("対象のログが見つかりません。")
    output_root = (
        args.output_root or LOGS_DIR / f"experiment_{datetime.now():%Y%m%d_%H%M%S}"
    )
    print(f"output: {output_root}")
    print(f"logs: {len(jobs)}（{', '.join(sorted(methods))}）", flush=True)
    if args.dry_run:
        return

    semaphore = asyncio.Semaphore(max(1, args.concurrency))
    results = await asyncio.gather(
        *[
            process_one(p, r, output_root=output_root, semaphore=semaphore)
            for p, r in jobs
        ]
    )
    counts: dict[tuple[str, str], int] = {}
    for key in results:
        counts[key] = counts.get(key, 0) + 1
    for (method, path_name), value in sorted(counts.items()):
        print(f"  {method} / {path_name}: {value}")
    print(f"saved -> {output_root}")


if __name__ == "__main__":
    asyncio.run(main())
