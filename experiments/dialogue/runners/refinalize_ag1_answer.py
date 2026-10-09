"""既存の議論ログの最終回答だけを、AG1 の役割で書き直す（議論と統合案はそのまま使う）.

real_final などの議論をそのまま使い、最終回答の書き手だけを、中立な書き手から AG1 に替えて作り直す。
統合案は、ログに保存済みの ``integrated_proposal`` を再利用する（統合を作り直さないので、最終回答の書き手以外は
変わらない）。元のログは書き換えず、出力先に新しいファイルとして保存する。

- ``final_answer``: AG1 の役割で書いた新しい最終回答。
- ``neutral_final_answer``: 元の（中立な書き手の）最終回答。
- ``final_answer_writer``: ``"AG1"``。

出力は ``<出力先>/turns<N>/raw_dialogue/<カテゴリ>/<トピック>/<元と同じファイル名>``。

Usage:
    python -m experiments.dialogue.runners.refinalize_ag1_answer \
      --source logs/real_final --output-root logs/real_final_ag1 [--limit 3] [--dry-run]
"""

# ruff: noqa: T201

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from experiments.dialogue.runners.refinalize_unified_final import justified_argument_of  # noqa: E402
from src.agent.final_answer import answer_from_materials  # noqa: E402

WRITER = "AG1"
DEFAULT_METHODS = ("schema", "no_schema", "free_debate", "mad_synthesis")


async def rewrite(log: dict[str, Any], *, writer: str = WRITER) -> dict[str, Any]:
    """1 つのログの最終回答を、writer の役割で書き直した、新しいログを返す（統合案は保存済みのものを使う）."""
    justified = justified_argument_of(log)
    proposal = None if justified else log.get("integrated_proposal")
    answer = await answer_from_materials(
        question=str(log.get("question", "")),
        agent1_stance=str(log.get("agent1_stance", "")),
        agent2_stance=str(log.get("agent2_stance", "")),
        dialogue_history=list(log.get("dialogue_history") or []),
        integrated_proposal=proposal
        if isinstance(proposal, str) and proposal.strip()
        else None,
        justified_argument=justified,
        writer=writer,
    )
    copied = dict(log)
    copied["neutral_final_answer"] = log.get("final_answer")
    copied["final_answer"] = answer
    copied["final_answer_writer"] = writer
    return copied


def collect(source: Path, methods: frozenset[str]) -> list[tuple[Path, Path]]:
    """``(元のログ, source からの相対パス)`` を返す。手法はログの method で判定する."""
    found: list[tuple[Path, Path]] = []
    for path in sorted(source.glob("turns*/raw_dialogue/*/*/*.json")):
        if json.loads(path.read_text(encoding="utf-8")).get("method") in methods:
            found.append((path, path.relative_to(source)))
    return found


async def process_one(
    path: Path, relative: Path, *, output_root: Path, semaphore: asyncio.Semaphore
) -> str:
    """1 本を書き直して保存し、手法名を返す."""
    async with semaphore:
        original = json.loads(path.read_text(encoding="utf-8"))
        log = await rewrite(original)
        log["rewritten_from"] = str(path.resolve())
        out = output_root / relative
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return str(original.get("method"))


async def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--source",
        type=Path,
        required=True,
        help="議論のログのあるフォルダ（例: logs/real_final）。",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        required=True,
        help="出力先（元のフォルダとは別にする）。",
    )
    parser.add_argument(
        "--methods",
        default=",".join(DEFAULT_METHODS),
        help="対象の手法を ',' 区切りで。",
    )
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument(
        "--limit", type=int, default=None, help="試運転用: 処理するログ数の上限。"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="LLM を呼ばず、対象の件数だけ表示する。"
    )
    args = parser.parse_args()

    if args.output_root.resolve() == args.source.resolve():
        raise SystemExit(
            "--output-root は --source と別のフォルダにしてください（上書きしません）。"
        )
    methods = frozenset(m.strip() for m in args.methods.split(",") if m.strip())
    jobs = collect(args.source, methods)
    if args.limit is not None:
        jobs = jobs[: args.limit]
    if not jobs:
        raise SystemExit("対象のログが見つかりません。")
    print(f"output: {args.output_root}")
    print(f"logs: {len(jobs)}（{', '.join(sorted(methods))}）", flush=True)
    if args.dry_run:
        return

    semaphore = asyncio.Semaphore(max(1, args.concurrency))
    results = await asyncio.gather(
        *[
            process_one(p, r, output_root=args.output_root, semaphore=semaphore)
            for p, r in jobs
        ]
    )
    for method in sorted(set(results)):
        print(f"  {method}: {results.count(method)}")
    print(f"saved -> {args.output_root}")


if __name__ == "__main__":
    asyncio.run(main())
