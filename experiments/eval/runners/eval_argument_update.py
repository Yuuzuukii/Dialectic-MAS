"""各発言が、相手の反論を受けて、自分の主張を意味的に更新しているかを判定する.

発言の「言及の形式」ではなく「意味内容の変化」を見る。DQI の反論への敬意が、相手への明示的な言及の有無という
表現の違い（schema は規則列で答えるため言及が少ない）を拾ってしまった反省から作った。

判定者に渡すのは次の3点（手法名・攻撃の種類・決着状態・初期スタンスは見せない）。

- 採点する発言の話者が、それより前に出した発言（自分の過去の主張）。
- 直前の相手の発言（相手の反論）。
- 採点する発言。

判定項目（構造化出力。理由の文を必ず返させ、後から読んで検証できるようにする）。

- ``responds``: 相手の発言の内容に、中身で応答しているか。相手に明示的に言及していなくてもよい。
- ``updates``: 相手の反論を受けて、自分のそれまでの主張を、変更・限定・修正・拡張しているか。
  同じ立場や同じ導出を言い直すだけ、別の等価な反論を出すだけ、は更新としない。
- ``update_kind``: 更新の種類。``none`` / ``concedes_or_qualifies`` / ``narrows_disagreement`` /
  ``adds_proposition_or_condition`` / ``other``。
- ``what_changed``: 何が変わったか（更新なしなら空）。

採点の単位: 同じ陣営の過去の発言があり、かつ、相手の発言が先にある発言。

出力は ``<source>/turns<N>/eval_result/argument_update/argument_update.json``。

Usage:
    python -m experiments.eval.runners.eval_argument_update \
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

from experiments.eval.runners.eval_turn_novelty import collect, parse_source
from experiments.eval.runners.run_eval import resolve_evaluator_model
from src.agent.dialogue_transcript import render_argument_text

PROMPT = """Below is part of a debate on the question. Two sides, AG1 and AG2, argue in turn. You are shown one
turn by {agent} (the turn under review), the argument by the other side that came just before it, and {agent}'s own
earlier turns.

Judge the MEANING of the turn, not its wording or format. Some turns are written as plain prose, others as a chain of
conditions and conclusions; treat them the same. Do not reward explicit discourse markers such as "I agree", "your
point", or "the opponent argues". Do not penalize structured or rule-based formulations that respond to the same
content without such phrases.

Decide:

1. responds: does the turn respond to the content of the other side's argument (answers it, accepts part of it,
   or rebuts its substance)? It counts even if the turn never mentions, quotes, or refers to the other side. It does
   not count if the turn ignores that content and just pursues its own line.

2. updates: in response to the other side, does the turn CHANGE what {agent}'s argument asserts or depends on
   compared with {agent}'s earlier turns? Count a change that concedes or qualifies a point, narrows what the two sides
   actually disagree about, or adds a proposition or condition that {agent}'s earlier turns did not contain. Do not
   count restating the same position or derivation, rewording it, adding an example of an idea already stated, or
   giving another rebuttal that rests on the same reasoning as an earlier turn.

3. update_kind: if updates is true, choose the kind. concedes_or_qualifies = gives up or limits an earlier claim.
   narrows_disagreement = states more exactly what is and is not disputed. adds_proposition_or_condition = introduces
   a new intermediate proposition, condition, or distinction. other = a change that fits none of these. If updates
   is false, choose none.

4. what_changed: in one sentence, say what changed compared with {agent}'s earlier turns (empty if nothing changed).

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


class UpdateJudgement(BaseModel):
    """1 発言についての判定."""

    responds: bool = Field(
        description="Whether the turn responds to the content of the other side's argument, with or without naming it."
    )
    updates: bool = Field(
        description="Whether the turn changes what the speaker's argument asserts or depends on, in response to the other side."
    )
    update_kind: Literal[
        "none",
        "concedes_or_qualifies",
        "narrows_disagreement",
        "adds_proposition_or_condition",
        "other",
    ] = Field(description="The kind of change; none when updates is false.")
    what_changed: str = Field(
        description="One sentence on what changed compared with the speaker's earlier turns; empty if nothing changed."
    )


def applicable_turns(history: list[dict[str, Any]]) -> list[int]:
    """同じ陣営の過去の発言があり、かつ、相手の発言が先にある発言の位置（0 始まり）."""
    out: list[int] = []
    for index, turn in enumerate(history):
        agent = turn.get("agent")
        earlier = history[:index]
        if any(t.get("agent") == agent for t in earlier) and any(t.get("agent") != agent for t in earlier):
            out.append(index)
    return out


def last_opponent_turn(history: list[dict[str, Any]], index: int) -> int:
    """直前の相手の発言の位置。applicable_turns の発言でだけ呼ぶ."""
    agent = history[index].get("agent")
    return max(i for i in range(index) if history[i].get("agent") != agent)


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


def _judge(model_name: str, prompt: str) -> UpdateJudgement:
    structured = ChatOpenAI(model=model_name).with_structured_output(UpdateJudgement)
    result = structured.invoke(prompt)
    return result if isinstance(result, UpdateJudgement) else UpdateJudgement.model_validate(result)


def evaluate_log(model_name: str, path: Path) -> dict[str, Any]:
    """1 つのログの、対象の発言すべてを判定する。1 発言の失敗は responds=None で記録して続ける."""
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
            rows.append(
                {**base, "responds": None, "updates": None, "update_kind": None, "what_changed": f"failed: {exc}"}
            )
            continue
        rows.append({**base, **judgement.model_dump()})
    judged = [r for r in rows if r["responds"] is not None]
    return {
        "file": path.name,
        "topic": path.parent.name,
        "category": path.parent.parent.name,
        "method": log.get("method"),
        "n_judged": len(judged),
        "n_failed": len(rows) - len(judged),
        "responds_rate": round(sum(r["responds"] for r in judged) / len(judged), 4) if judged else None,
        "update_rate": round(sum(r["updates"] for r in judged) / len(judged), 4) if judged else None,
        "turns": rows,
    }


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    """手法ごとの応答率・更新率（ログごとの率の平均）、更新の種類の内訳、発言の種類別・前半後半別の更新率."""
    summary: dict[str, Any] = {}
    for method in sorted({str(r["method"]) for r in results}):
        logs = [r for r in results if r["method"] == method and r["update_rate"] is not None]
        kinds: dict[str, int] = defaultdict(int)
        by_type: dict[str, list[bool]] = defaultdict(list)
        halves: dict[str, list[bool]] = defaultdict(list)
        for log in logs:
            middle = max((t["turn"] for t in log["turns"]), default=0) / 2
            for turn in (t for t in log["turns"] if t["responds"] is not None):
                kinds[turn["update_kind"]] += 1
                by_type[str(turn["type"])].append(turn["updates"])
                halves["first_half" if turn["turn"] <= middle else "second_half"].append(turn["updates"])
        total = sum(kinds.values())
        summary[method] = {
            "n_logs": len(logs),
            "responds_rate_mean": round(st.mean(r["responds_rate"] for r in logs), 4) if logs else None,
            "update_rate_mean": round(st.mean(r["update_rate"] for r in logs), 4) if logs else None,
            "updates_per_log": round(st.mean(sum(t["updates"] is True for t in r["turns"]) for r in logs), 2)
            if logs
            else None,
            "update_kind_share": {k: round(v / total, 4) for k, v in sorted(kinds.items())} if total else {},
            "update_rate_by_turn_type": {k: round(sum(v) / len(v), 4) for k, v in sorted(by_type.items())},
            "update_rate_by_half": {k: round(sum(v) / len(v), 4) for k, v in sorted(halves.items())},
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
        out = turn_dir / "eval_result" / "argument_update" / "argument_update.json"
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
