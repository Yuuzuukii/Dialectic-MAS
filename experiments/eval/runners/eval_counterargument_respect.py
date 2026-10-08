"""各発言が、相手の反論をどう扱っているかを、DQI の「反論への敬意」で評価する.

Discourse Quality Index（Steenbergen, Bächtiger, Spörndli, Steiner 2003, p. 29）の
respect toward counterarguments を、段階（0〜3）のまま使う。論文は、反論が出ている場合だけ採点する。

- 0 Counterarguments ignored: 反論があるのに、無視する（反論の主張に答えていない）。
- 1 Included but degraded: 取り上げるが、反論や、それを出した人・集団を貶める発言がある。
- 2 Included, neutral: 取り上げて、肯定的にも否定的にも評価しない。
- 3 Included and valued: 取り上げて、明示的に評価する（否定的な発言が併存しても 3）。

論文の段階を、TypeSafe の Jev（System One）の Noul 質問 3 つに分け、「yes である確率」を得る。

- ``acknowledges`` : 相手の反論の中身に触れ、言及・言い直しなどで、その反論を認識したことを示している（無視していない）。偽なら段階 0。
- ``valued``    : 相手の主張を、明示的に評価している（重要・妥当・合理的・有用など、検討に値すると述べる。反対していても可）。
- ``degraded``  : 相手の主張や、それを出した人を、明示的に貶めている（蔑む、悪意と決めつけるなど）。

段階: ``acknowledges`` < 閾値なら 0。そうでなければ ``valued`` >= 閾値なら 3、``degraded`` >= 閾値なら 1、それ以外は 2。
期待値 ``expected_level = a·(3v + (1-v)·(d·1 + (1-d)·2))``（a=acknowledges, v=valued, d=degraded）は閾値を使わない。

論文との違い: 論文は「否定的な発言が 1 つでもあれば 1」とするが、議論では、相手の前提が成り立たない・結論が出ないと
指摘すること自体が反論の役割なので、これは貶めに数えない（質問文で明示）。蔑み・決めつけなど、主張の中身でなく
相手を貶める発言だけを 1 とする。

採点の単位: 相手の側の過去の発言がある発言（最初の発言など、反論が出ていない発言は対象外）。
判定者には、問い・それまでの議論・直前の相手の発言・採点する発言を、手法に依らない同じ書き起こしで渡す。
手法名、攻撃の種類、決着状態、初期スタンスは見せない。反論として答える相手は、直前の相手の発言とする。

注意: この指標は、反論への応じ方を測る。応答が、議論を前に進めたかは測らない。

出力は ``<source>/turns<N>/eval_result/counterargument_respect/counterargument_respect.json``。

環境変数: TYPESAFE_API_KEY（.env から読む）。

Usage:
    python -m experiments.eval.runners.eval_counterargument_respect \
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
    "acknowledges": (
        "The turn under review acknowledges the specific content of the other side's argument shown as "
        "'other_sides_argument': it refers to, restates, or otherwise makes clear that the argument has been "
        "recognized. A turn that ignores that argument or proceeds without engaging with its content does not count."
    ),
    "valued": (
        "The turn under review explicitly values the other side's argument: it states that the point is important, "
        "valid, reasonable, useful, or otherwise worthy of consideration. This counts even if the turn also "
        "disagrees with the argument."
    ),
    "degraded": (
        "The turn under review explicitly degrades the other side's argument or the people who made it: it "
        "disparages, ridicules, dismisses, or attributes bad faith to the argument or its proponents. Merely arguing "
        "that a premise is false, that a conclusion does not follow, or that the argument is mistaken, when this is "
        "done as substantive disagreement rather than disparagement, does not count."
    ),
}


def applicable_turns(history: list[dict[str, Any]]) -> list[int]:
    """相手の側の過去の発言がある発言の位置（0 始まり）。反論が出ていない発言は対象外."""
    out: list[int] = []
    for index, turn in enumerate(history):
        if any(history[i].get("agent") != turn.get("agent") for i in range(index)):
            out.append(index)
    return out


def last_opponent_turn(history: list[dict[str, Any]], index: int) -> int:
    """直前の相手の発言の位置。applicable_turns の発言でだけ呼ぶ."""
    agent = history[index].get("agent")
    return max(i for i in range(index) if history[i].get("agent") != agent)


def build_state(
    log: dict[str, Any], history: list[dict[str, Any]], index: int
) -> dict[str, str]:
    """Jev に渡す入力。採点する発言、答える相手の発言、それまでの議論を分けて渡す（初期スタンスは渡さない）."""
    target = last_opponent_turn(history, index)
    return {
        "question": str(log.get("question") or ""),
        "transcript_format": TRANSCRIPT_DESCRIPTION,
        "earlier_dialogue": format_transcript(history[:index]),
        "speaker": str(history[index].get("agent")),
        "other_sides_argument": f"[Turn {target + 1}]\n{render_argument_text(history[target].get('argument'))}",
        "turn_under_review": f"[Turn {index + 1}]\n{render_argument_text(history[index].get('argument'))}",
    }


def level_of(
    p_acknowledges: float, p_valued: float, p_degraded: float, threshold: float
) -> int:
    """論文の段階（0〜3）。取り上げていなければ 0、評価していれば 3、貶していれば 1、それ以外は 2."""
    if p_acknowledges < threshold:
        return 0
    if p_valued >= threshold:
        return 3
    if p_degraded >= threshold:
        return 1
    return 2


def expected_level(p_acknowledges: float, p_valued: float, p_degraded: float) -> float:
    """閾値を使わない連続値。取り上げていれば 3 / 1 / 2 を確率で重み付け、取り上げていなければ 0."""
    inside = 3 * p_valued + (1 - p_valued) * (p_degraded * 1 + (1 - p_degraded) * 2)
    return p_acknowledges * inside


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
    """1 つのログの、対象の発言すべてを採点する。1 発言の失敗は None で記録して続ける."""
    log = json.loads(path.read_text(encoding="utf-8"))
    history = list(log.get("dialogue_history") or [])

    async def one(index: int) -> dict[str, Any]:
        async with semaphore:
            probs = await judge_turn(client, build_state(log, history, index))
        base = {
            "turn": index + 1,
            "agent": history[index].get("agent"),
            "type": history[index].get("type"),
            "answers_turn": last_opponent_turn(history, index) + 1,
        }
        if probs is None:
            return {
                **base,
                "acknowledges": None,
                "valued": None,
                "degraded": None,
                "level": None,
                "expected_level": None,
            }
        return {
            **base,
            **probs,
            "level": level_of(
                probs["acknowledges"], probs["valued"], probs["degraded"], threshold
            ),
            "expected_level": round(
                expected_level(probs["acknowledges"], probs["valued"], probs["degraded"]),
                4,
            ),
        }

    rows = list(await asyncio.gather(*(one(i) for i in applicable_turns(history))))
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
        "acknowledges_mean": round(st.mean(r["acknowledges"] for r in valid), 4)
        if valid
        else None,
        "valued_mean": round(st.mean(r["valued"] for r in valid), 4) if valid else None,
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
            middle = max(t["turn"] for t in log["turns"]) / 2 if log["turns"] else 0
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
            "acknowledges_mean": round(st.mean(r["acknowledges_mean"] for r in logs), 4)
            if logs
            else None,
            "valued_mean": round(st.mean(r["valued_mean"] for r in logs), 4)
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
        len(
            applicable_turns(
                json.loads(p.read_text(encoding="utf-8")).get("dialogue_history") or []
            )
        )
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
            / "counterargument_respect"
            / "counterargument_respect.json"
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
