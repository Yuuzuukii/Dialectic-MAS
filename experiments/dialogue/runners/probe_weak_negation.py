"""schema の最初の主張（main）で weak_negation が使われない理由を、モデル自身に聞く簡易プローブ.

議論は回さない。トピックごとに、(1) 通常どおり main を1本生成し、(2) その生成物を履歴に載せて
「なぜ weak_negation を使った／使わなかったか」「定義は自分の推論に合うか」を自由文で答えさせる。
結果は標準出力に出し、``--out`` を指定したときだけ JSON に保存する（既定は保存しない）。

LLM 呼び出しは 1 トピックあたり 2 回（構造化 1 + 自由文 1）。

Usage:
    python -m experiments.dialogue.runners.probe_weak_negation \
      datasets/Education/animal_dissection.json datasets/Environment_Animal_Rights/alternative_energy.json \
      [--samples 2] [--out scratch.json]
"""

# ruff: noqa: T201

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from langchain_core.messages import AIMessage, HumanMessage  # noqa: E402

from src.agent.arguments import build_main_argument_messages, generate_main  # noqa: E402
from src.agent.dialogue_transcript import render_argument_text  # noqa: E402
from src.agent.llm import chat_text  # noqa: E402
from src.agent.schema.types import AgentName  # noqa: E402

FOLLOW_UP = (
    "This is a follow-up question about the Argument you just produced; it is not a debate turn, "
    "so do not produce a new Argument.\n\n"
    "The schema lets an antecedent hold strong premises and weak_negation entries. "
    "Please answer candidly, in your own words:\n"
    "1. Did you use weak_negation in that Argument? If you did not, why not?\n"
    "2. Did you hold any assumption that your conclusion depends on (a premise you took for granted "
    "rather than established, or a condition under which the conclusion would fail) but wrote it as a "
    "strong premise or left it out? If so, name it.\n"
    "3. Does the definition of weak_negation in your instructions fit how you actually reason about this "
    "topic? What would make it easier or harder to use?"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("topic_files", nargs="+", type=Path, help="トピック JSON（複数可）。")
    parser.add_argument("--samples", type=int, default=1, help="トピックごとの試行回数。")
    parser.add_argument("--agent", choices=("AG1", "AG2"), default="AG1")
    parser.add_argument("--no-follow-up", action="store_true", help="質問せず、main の生成と weak_negation の有無だけ数える。")
    parser.add_argument("--out", type=Path, default=None, help="指定したときだけ結果を JSON に保存する。")
    return parser.parse_args()


def _has_weak(argument_json: str) -> bool:
    body = json.loads(argument_json)
    body = body.get("Argument", body)
    return any((rule.get("antecedent") or {}).get("weak_negation") for rule in body.get("rules", []))


async def probe_once(topic: dict[str, Any], agent: AgentName, *, follow_up: bool) -> dict[str, Any]:
    state = SimpleNamespace(
        question=topic["question"],
        agent1_stance=topic["agent1_stance"],
        agent2_stance=topic["agent2_stance"],
        debate_round=1,
        history=[],
        integrated_rules=[],
        output_mode="schema",
    )
    generation = await generate_main(state, agent)
    if generation.argument is None:
        return {"question": topic["question"], "generated": False, "reason": generation.reason}
    used = _has_weak(generation.argument.argument)
    if not follow_up:
        return {
            "question": topic["question"],
            "generated": True,
            "used_weak_negation": used,
            "argument": render_argument_text(generation.argument.argument),
            "answer": "",
        }
    messages = build_main_argument_messages(state, agent)
    messages += [
        AIMessage(content=render_argument_text(generation.argument.argument)),
        HumanMessage(content=FOLLOW_UP),
    ]
    answer = await chat_text(messages)
    return {
        "question": topic["question"],
        "generated": True,
        "used_weak_negation": _has_weak(generation.argument.argument),
        "argument": render_argument_text(generation.argument.argument),
        "answer": answer,
    }


async def main() -> None:
    args = parse_args()
    topics = [json.loads(path.read_text(encoding="utf-8")) for path in args.topic_files]
    jobs = [probe_once(topic, cast(AgentName, args.agent), follow_up=not args.no_follow_up) for topic in topics for _ in range(args.samples)]
    results = await asyncio.gather(*jobs)
    for result in results:
        print("=" * 80)
        print(f"topic: {result['question']}")
        if not result["generated"]:
            print(f"(main not generated: {result['reason']})")
            continue
        print(f"used weak_negation: {result['used_weak_negation']}")
        print("-" * 30, "argument")
        print(result["argument"])
        if result["answer"]:
            print("-" * 30, "model's answer")
            print(result["answer"])
    used = sum(r.get("used_weak_negation", False) for r in results)
    print("=" * 80)
    print(f"weak_negation used: {used}/{len(results)}")
    if args.out is not None:
        args.out.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"saved -> {args.out}")


if __name__ == "__main__":
    asyncio.run(main())
