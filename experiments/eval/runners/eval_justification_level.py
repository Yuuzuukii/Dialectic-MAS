"""各発言の主張が、どの程度完全に正当化されているかを、DQI の「正当化の水準」で評価する.

Discourse Quality Index（Steenbergen, Bächtiger, Spörndli, Steiner 2003, p. 28）の
level of justification を、段階（0〜3）のまま使う。

- 0 No justification: 主張するだけで、理由がない。
- 1 Inferior justification: 理由は挙げるが、主張との結びつきがない（推論が不完全）。
  例や図解で主張を支えるだけの場合もここ。
- 2 Qualified justification: 主張と理由の結びつきが 1 つ示されている（完全な推論が 1 つ）。
- 3 Sophisticated justification: 完全な推論が 2 つ以上ある（同じ主張に 2 つ、または別の 2 つの主張に 1 つずつ）。

論文の段階を、TypeSafe の Jev（System One）の Noul 質問 3 つに分け、「yes である確率」を得る。
質問は入れ子になっている（上の段階ほど条件が厳しい）。確率は 0.5 付近が確信のない判定。

- ``reason``   : 理由を 1 つ以上挙げている（段階 1 以上）。
- ``complete`` : 理由と主張の結びつきを示す、完全な推論が 1 つ以上ある（段階 2 以上）。
- ``two``      : 完全な推論が 2 つ以上ある（段階 3）。

段階は、条件を満たす最も高いものを採る（``two`` >= 閾値なら 3、``complete`` >= 閾値なら 2、
``reason`` >= 閾値なら 1、それ以外は 0）。期待値 ``expected_level`` は、入れ子になるよう
確率を上から押さえた和 ``a + min(a, b) + min(a, b, c)``（a=reason, b=complete, c=two）で、閾値を使わない。

採点の単位は発言。判定者には、問い・それまでの議論・採点する発言を、手法に依らない同じ書き起こし
（:mod:`src.agent.dialogue_transcript`）で渡す。手法名、攻撃の種類、決着状態、陣営の初期スタンスは見せない。

注意: この指標は、論証が完結しているか（結論と理由の結びつきが書かれているか）を測る。
例だけで支える発言は 1 になるため、結論の成立条件を明示する書き方に有利に出る。新しい論点を足したかは測らない。

出力は ``<source>/turns<N>/eval_result/justification_level/justification_level.json``。

環境変数: TYPESAFE_API_KEY（.env から読む）。

Usage:
    python -m experiments.eval.runners.eval_justification_level \
      --source logs/final:schema,no_schema,free_debate,mad,mad_synthesis [--turns 20] [--limit 2]
"""

# ruff: noqa: T201, E402, I001

from __future__ import annotations

import argparse
import asyncio
import json
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from experiments.eval.runners.eval_turn_novelty import collect, parse_source
from src.agent.dialogue_transcript import (
    TRANSCRIPT_DESCRIPTION,
    format_transcript,
    render_argument_text,
)

from typesafe_sdk import AsyncTypeSafeClient, Noul, NoulAnswer, TypeSafeError

NOUL_QUESTIONS = {
    "reason": (
        "In the turn under review, the speaker gives at least one reason or consideration in support of the claim "
        "the turn asserts. A bare assertion, or a statement that something should or should not be done with no "
        "supporting reason or consideration, does not count."
    ),
    "complete": (
        "In the turn under review, the speaker makes at least one complete inference: a reason together with an "
        "explicit or unambiguously implicit link showing why that reason supports the claim, for example, why X "
        "contributes to or detracts from Y. A fact, example, or illustration offered in support of the claim does "
        "not count as a complete inference unless the link to the claim is explicit or beyond reasonable doubt "
        "from the context."
    ),
    "two": (
        "In the turn under review, the speaker gives at least two complete justifications: either two complete "
        "justifications for the same claim, or complete justifications for two different claims. A complete "
        "justification consists of a reason together with an explicit or unambiguously implicit link showing why "
        "that reason supports the claim."
    ),
}


def build_state(
    log: dict[str, Any], history: list[dict[str, Any]], index: int
) -> dict[str, str]:
    """Jev に渡す入力。採点する発言と、それまでの議論（書き起こし）を分けて渡す（初期スタンスは渡さない）."""
    earlier = format_transcript(history[:index]) if index else "(no earlier turns)"
    return {
        "question": str(log.get("question") or ""),
        "transcript_format": TRANSCRIPT_DESCRIPTION,
        "earlier_dialogue": earlier,
        "speaker": str(history[index].get("agent")),
        "turn_under_review": f"[Turn {index + 1}]\n{render_argument_text(history[index].get('argument'))}",
    }


def level_of(p_reason: float, p_complete: float, p_two: float, threshold: float) -> int:
    """論文の段階（0〜3）。条件を満たす最も高い段階を採る."""
    if p_two >= threshold:
        return 3
    if p_complete >= threshold:
        return 2
    if p_reason >= threshold:
        return 1
    return 0


def expected_level(p_reason: float, p_complete: float, p_two: float) -> float:
    """閾値を使わない連続値。上の段階の確率が下の段階を超えないよう押さえた和（P(段階>=k) の和）."""
    complete = min(p_reason, p_complete)
    two = min(complete, p_two)
    return p_reason + complete + two


async def judge_turn(
    client: AsyncTypeSafeClient, state: dict[str, str]
) -> dict[str, float] | None:
    """1 発言の Noul 確率。失敗は None."""
    questions = {key: Noul(instructions=text) for key, text in NOUL_QUESTIONS.items()}
    try:
        response = await client.system_one(state, questions)
    except TypeSafeError as exc:
        print(f"Jev judgement failed: {exc}", flush=True)
        return None
    answers = {key: response.answers[key] for key in NOUL_QUESTIONS}
    if not all(isinstance(a, NoulAnswer) for a in answers.values()):
        return None
    return {
        key: float(a.noul) for key, a in answers.items() if isinstance(a, NoulAnswer)
    }


async def evaluate_log(
    client: AsyncTypeSafeClient,
    semaphore: asyncio.Semaphore,
    path: Path,
    threshold: float,
) -> dict[str, Any]:
    """1 つのログの、全発言を採点する。1 発言の失敗は None で記録して続ける."""
    log = json.loads(path.read_text(encoding="utf-8"))
    history = list(log.get("dialogue_history") or [])

    async def one(index: int) -> dict[str, Any]:
        async with semaphore:
            probs = await judge_turn(client, build_state(log, history, index))
        base = {
            "turn": index + 1,
            "agent": history[index].get("agent"),
            "type": history[index].get("type"),
        }
        if probs is None:
            return {
                **base,
                "reason": None,
                "complete": None,
                "two": None,
                "level": None,
                "expected_level": None,
            }
        return {
            **base,
            **probs,
            "level": level_of(
                probs["reason"], probs["complete"], probs["two"], threshold
            ),
            "expected_level": round(
                expected_level(probs["reason"], probs["complete"], probs["two"]), 4
            ),
        }

    rows = list(await asyncio.gather(*(one(i) for i in range(len(history)))))
    valid = [r for r in rows if r["level"] is not None]
    return {
        "file": path.name,
        "topic": path.parent.name,
        "category": path.parent.parent.name,
        "method": log.get("method"),
        "n_turns": len(rows),
        "n_failed": len(rows) - len(valid),
        "level_mean": round(st.mean(r["level"] for r in valid), 4) if valid else None,
        "expected_level_mean": round(st.mean(r["expected_level"] for r in valid), 4)
        if valid
        else None,
        "turns": rows,
    }


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    """手法ごとの平均（ログごとの平均の平均）、段階の内訳、発言の種類別・議論の前半後半別の平均."""
    summary: dict[str, Any] = {}
    for method in sorted({str(r["method"]) for r in results}):
        logs = [
            r for r in results if r["method"] == method and r["level_mean"] is not None
        ]
        counts: dict[int, int] = defaultdict(int)
        by_type: dict[str, list[float]] = defaultdict(list)
        halves: dict[str, list[float]] = defaultdict(list)
        for log in logs:
            middle = len(log["turns"]) / 2
            for turn in (t for t in log["turns"] if t["level"] is not None):
                counts[turn["level"]] += 1
                by_type[str(turn["type"])].append(turn["level"])
                halves[
                    "first_half" if turn["turn"] <= middle else "second_half"
                ].append(turn["level"])
        total = sum(counts.values())
        summary[method] = {
            "n_logs": len(logs),
            "level_mean": round(st.mean(r["level_mean"] for r in logs), 4)
            if logs
            else None,
            "expected_level_mean": round(
                st.mean(r["expected_level_mean"] for r in logs), 4
            )
            if logs
            else None,
            "level_share": {
                str(k): round(v / total, 4) for k, v in sorted(counts.items())
            }
            if total
            else {},
            "level_by_turn_type": {
                k: round(st.mean(v), 4) for k, v in sorted(by_type.items())
            },
            "level_by_half": {
                k: round(st.mean(v), 4) for k, v in sorted(halves.items())
            },
        }
    return summary


async def _run(args: argparse.Namespace) -> None:
    turns = {int(t) for t in args.turns.split(",") if t.strip()} if args.turns else None
    paths: list[Path] = []
    for root, methods in args.source:
        found = collect(root.resolve(), set(methods), turns)
        paths += found[: args.limit] if args.limit else found
    calls = sum(
        len(json.loads(p.read_text(encoding="utf-8")).get("dialogue_history") or [])
        for p in paths
    )
    print(
        f"{len(paths)} ログ、約 {calls} 回の判定（Jev, concurrency={args.concurrency}）",
        flush=True,
    )

    semaphore = asyncio.Semaphore(args.concurrency)
    results: list[tuple[Path, dict[str, Any]]] = []

    async def run_one(
        client: AsyncTypeSafeClient, path: Path
    ) -> tuple[Path, dict[str, Any]]:
        return path, await evaluate_log(client, semaphore, path, args.threshold)

    async with AsyncTypeSafeClient() as client:
        for done in asyncio.as_completed([run_one(client, p) for p in paths]):
            path, row = await done
            results.append((path, row))
            print(
                f"[{len(results):03d}/{len(paths)}] {path.parent.name}/{path.name}",
                flush=True,
            )

    by_turns: dict[Path, list[dict[str, Any]]] = defaultdict(list)
    for path, row in results:
        by_turns[path.parents[3]].append(row)
    for turn_dir, rows in sorted(by_turns.items()):
        rows.sort(key=lambda r: (r["topic"], str(r["method"]), r["file"]))
        out = (
            turn_dir
            / "eval_result"
            / "justification_level"
            / "justification_level.json"
        )
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(
                {
                    "threshold": args.threshold,
                    "summary": summarize(rows),
                    "detail": rows,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"Saved: {out}")
    print("\n手法ごとの結果（全ターン数まとめ）:")
    for method, agg in summarize([row for _, row in results]).items():
        print(f"  {method:<14} {json.dumps(agg, ensure_ascii=False)}")


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--source",
        action="append",
        type=parse_source,
        required=True,
        help="<実験フォルダ>:<手法,手法>（複数可）。",
    )
    parser.add_argument(
        "--turns",
        default=None,
        help="対象のターン数を ',' 区切りで（例: 20）。省略で全部。",
    )
    parser.add_argument(
        "--threshold", type=float, default=0.5, help="段階を決める確信度の閾値。"
    )
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="試運転用: 各 --source で評価するログ数の上限。",
    )
    asyncio.run(_run(parser.parse_args()))


if __name__ == "__main__":
    main()
