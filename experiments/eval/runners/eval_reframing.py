"""各発言が、対立を定義・評価基準・争点の捉え直しによって再構成しているかを判定する.

argument_update は「主張が変わったか」（限定・争点の絞り込み・命題の追加）を測る。こちらは、それとは別に、
「何をもって成り立つとするか」「問題は何か」という捉え方そのものを、新しく持ち込んでいるかを測る
（例: 「置き換え可能」とは何を指すかの定義、「対策の有無ではなく規模での実施可能性が問題」という争点の再構成、
「結果の平等ではなく機会の平等」という概念の捉え直し）。

入力と形式への配慮は eval_argument_update と同じ（その話者の過去の発言、直前の相手の発言、採点する発言。
手法名・攻撃の種類・決着状態・初期スタンスは見せない。語彙ではなく意味で判定する）。

判定項目（構造化出力。理由の文を返させ、後から読んで検証できるようにする）。

- ``reframes``: その話者の過去の発言にない、定義・評価基準・争点の捉え方を持ち込んでいるか。
  同じ捉え方の中で、事実・例・対策・条件を足すだけは、再構成としない。
- ``reframe_kind``: ``none`` / ``redefines_concept`` / ``introduces_criterion`` / ``restructures_issue``。
- ``what_reframed``: 何を、どう捉え直したか（なしなら空）。

出力は ``<source>/turns<N>/eval_result/reframing/reframing.json``。

Usage:
    python -m experiments.eval.runners.eval_reframing \
      --source logs/final:schema,no_schema,free_debate,mad,mad_synthesis [--turns 20] [--limit 2]
"""

# ruff: noqa: T201, E402, I001

from __future__ import annotations

import argparse
import json
import statistics as st
import sys
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Literal

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

load_dotenv(ROOT / ".env")

from experiments.eval.runners.eval_argument_update import applicable_turns, last_opponent_turn
from experiments.eval.runners.eval_turn_novelty import collect, parse_source
from experiments.eval.runners.run_eval import resolve_evaluator_model
from src.agent.dialogue_transcript import render_argument_text

PROMPT = """Below is part of a debate on the question. Two sides, AG1 and AG2, argue in turn. You are shown one
turn by {agent} (the turn under review), the argument by the other side that came just before it, and {agent}'s own
earlier turns.

Judge the MEANING of the turn, not its wording or format. Some turns are plain prose, others a chain of conditions and
conclusions; treat them the same. Do not reward words such as "criterion", "define", or "framing" by themselves, and do
not penalize turns that reframe without such words.

Decide whether the turn RECONSTRUCTS the dispute by bringing in a way of framing it that none of {agent}'s earlier
turns used. There are three kinds:

- redefines_concept: it states or changes what a key term means or what counts as it (for example, what "replace
  fossil fuels" or "equal opportunity" is taken to mean), and the argument then rests on that meaning.
- introduces_criterion: it introduces a standard for judging the question that earlier turns did not use (for example,
  "the test is whether it works at sufficient scale", not just whether it can work).
- restructures_issue: it says the real disagreement is about something other than what it had been treated as (for
  example, "the issue is not whether safeguards exist but whether they can be applied at scale").

Adding facts, examples, measures, or conditions WITHIN the same framing is not a reconstruction. Restating a framing
{agent} already used is not a reconstruction.

Answer reframes=true only if one of the three kinds applies; otherwise reframe_kind=none. In what_reframed, say in one
sentence what was reframed and how (empty if nothing).

<question>
{question}
</question>

<earlier_turns_by_{agent}>
{earlier}
</earlier_turns_by_{agent}>

<other_sides_argument>
{other}
</other_sides_argument>

<turn_under_review>
{turn}
</turn_under_review>"""


class ReframingJudgement(BaseModel):
    """1 発言についての判定."""

    reframes: bool = Field(
        description="Whether the turn brings in a definition, criterion, or issue framing that the speaker's earlier turns did not use."
    )
    reframe_kind: Literal["none", "redefines_concept", "introduces_criterion", "restructures_issue"] = Field(
        description="The kind of reconstruction; none when reframes is false."
    )
    what_reframed: str = Field(description="One sentence on what was reframed and how; empty if nothing.")


def build_prompt(question: str, history: list[dict[str, Any]], index: int) -> str:
    """Build the judge prompt: 自分の過去の発言、直前の相手の発言、採点する発言."""
    agent = str(history[index].get("agent"))
    target = last_opponent_turn(history, index)
    earlier = "\n\n".join(
        f"[Turn {i + 1}]\n{render_argument_text(history[i].get('argument'))}"
        for i in range(index)
        if history[i].get("agent") == agent
    )
    return PROMPT.format(
        agent=agent,
        question=question,
        earlier=earlier,
        other=f"[Turn {target + 1}]\n{render_argument_text(history[target].get('argument'))}",
        turn=f"[Turn {index + 1}]\n{render_argument_text(history[index].get('argument'))}",
    )


def _judge(model_name: str, prompt: str) -> ReframingJudgement:
    structured = ChatOpenAI(model=model_name).with_structured_output(ReframingJudgement)
    result = structured.invoke(prompt)
    return result if isinstance(result, ReframingJudgement) else ReframingJudgement.model_validate(result)


def evaluate_log(model_name: str, path: Path) -> dict[str, Any]:
    """1 つのログの、対象の発言すべてを判定する。1 発言の失敗は reframes=None で記録して続ける."""
    log = json.loads(path.read_text(encoding="utf-8"))
    history = list(log.get("dialogue_history") or [])
    rows: list[dict[str, Any]] = []
    for index in applicable_turns(history):
        base = {
            "turn": index + 1,
            "agent": history[index].get("agent"),
            "type": history[index].get("type"),
            "answers_turn": last_opponent_turn(history, index) + 1,
        }
        try:
            judgement = _judge(model_name, build_prompt(str(log.get("question", "")), history, index))
        except Exception as exc:  # noqa: BLE001 - 1 発言の失敗で全体を止めない
            print(f"failed: {path.name} turn {index + 1}: {exc}", flush=True)
            rows.append({**base, "reframes": None, "reframe_kind": None, "what_reframed": f"failed: {exc}"})
            continue
        rows.append({**base, **judgement.model_dump()})
    judged = [r for r in rows if r["reframes"] is not None]
    return {
        "file": path.name,
        "topic": path.parent.name,
        "category": path.parent.parent.name,
        "method": log.get("method"),
        "n_judged": len(judged),
        "n_failed": len(rows) - len(judged),
        "reframe_rate": round(sum(r["reframes"] for r in judged) / len(judged), 4) if judged else None,
        "n_reframes": sum(r["reframes"] is True for r in rows),
        "turns": rows,
    }


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    """手法ごとの再構成率（ログごとの率の平均）、1 ログあたりの回数、種類の内訳、発言の種類別の率."""
    summary: dict[str, Any] = {}
    for method in sorted({str(r["method"]) for r in results}):
        logs = [r for r in results if r["method"] == method and r["reframe_rate"] is not None]
        kinds: dict[str, int] = defaultdict(int)
        by_type: dict[str, list[bool]] = defaultdict(list)
        for log in logs:
            for turn in (t for t in log["turns"] if t["reframes"] is not None):
                kinds[turn["reframe_kind"]] += 1
                by_type[str(turn["type"])].append(turn["reframes"])
        total = sum(kinds.values())
        summary[method] = {
            "n_logs": len(logs),
            "reframe_rate_mean": round(st.mean(r["reframe_rate"] for r in logs), 4) if logs else None,
            "reframes_per_log": round(st.mean(r["n_reframes"] for r in logs), 2) if logs else None,
            "reframe_kind_share": {k: round(v / total, 4) for k, v in sorted(kinds.items())} if total else {},
            "reframe_rate_by_turn_type": {k: round(sum(v) / len(v), 4) for k, v in sorted(by_type.items())},
        }
    return summary


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--source", action="append", type=parse_source, required=True, help="<実験フォルダ>:<手法,手法>（複数可）。"
    )
    parser.add_argument("--turns", default=None, help="対象のターン数を ',' 区切りで（例: 20）。省略で全部。")
    parser.add_argument("--model", default=None, help="評価モデル（既定: 環境変数 MODEL）。")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--limit", type=int, default=None, help="試運転用: 各 --source で評価するログ数の上限。")
    args = parser.parse_args()

    turns = {int(t) for t in args.turns.split(",") if t.strip()} if args.turns else None
    model_name = resolve_evaluator_model(args.model)
    paths: list[Path] = []
    for root, methods in args.source:
        found = collect(root.resolve(), set(methods), turns)
        paths += found[: args.limit] if args.limit else found
    calls = sum(
        len(applicable_turns(json.loads(p.read_text(encoding="utf-8")).get("dialogue_history") or []))
        for p in paths
    )
    print(f"{len(paths)} ログ、約 {calls} 回の判定（{model_name}, workers={args.workers}）", flush=True)

    results: list[tuple[Path, dict[str, Any]]] = []
    lock = threading.Lock()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(evaluate_log, model_name, p): p for p in paths}
        for done, future in enumerate(as_completed(futures), start=1):
            with lock:
                results.append((futures[future], future.result()))
                print(f"[{done:03d}/{len(paths)}] {futures[future].parent.name}/{futures[future].name}", flush=True)

    by_turns: dict[Path, list[dict[str, Any]]] = defaultdict(list)
    for path, row in results:
        by_turns[path.parents[3]].append(row)
    for turn_dir, rows in sorted(by_turns.items()):
        rows.sort(key=lambda r: (r["topic"], str(r["method"]), r["file"]))
        out = turn_dir / "eval_result" / "reframing" / "reframing.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps({"summary": summarize(rows), "detail": rows}, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"Saved: {out}")
    print("\n手法ごとの結果（全ターン数まとめ）:")
    for method, agg in summarize([row for _, row in results]).items():
        print(f"  {method:<14} {json.dumps(agg, ensure_ascii=False)}")


if __name__ == "__main__":
    main()
