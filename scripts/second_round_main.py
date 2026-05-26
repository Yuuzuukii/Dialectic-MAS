"""2周目の can_generate_main を単体で動かすスクリプト。

Usage:
    python scripts/second_round_main.py
    python scripts/second_round_main.py --print-prompt
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.agent.nodes import can_generate_main
from src.agent.prompt_builders import build_main_argument_prompt
from src.agent.schema.state import ArgumentRecord
from src.agent.workflow import State
from src.cli import AG1_STANCE, AG2_STANCE, QUESTION

# ── 1周目データ ────────────────────────────────────────────

ARG_A = ArgumentRecord(
    id="arg-68491bf536",
    type="main",
    agent="AG1",
    argument=json.dumps({
        "Argument": {
            "rules": [
                {
                    "antecedent": {"strong": ["a is compact", "a is light"], "weak_negation": []},
                    "consequent": "we should buy camera a",
                }
            ],
            "Conc": ["we should buy camera a"],
            "Ass": [],
        }
    }, ensure_ascii=False),
)

ARG_B = ArgumentRecord(
    id="arg-992578f4ab",
    type="defeat",
    agent="AG2",
    attack="rebut",
    target_id="arg-68491bf536",
    target_field="Conc",
    target_statement="we should buy camera a",
    argument=json.dumps({
        "Argument": {
            "rules": [
                {
                    "antecedent": {"strong": ["a is out of stock"], "weak_negation": []},
                    "consequent": "we should not buy camera a",
                }
            ],
            "Conc": ["we should not buy camera a"],
            "Ass": [],
        }
    }, ensure_ascii=False),
)

INTEGRATED_RULE = "If an object is compact or light or has log battery or high image quality or not over budget, then we should buy it."


def build_state() -> State:
    return State(
        question=QUESTION,
        agent1_stance=AG1_STANCE,
        agent2_stance=AG2_STANCE,
        debate_round=2,
        current_proponent="AG1",
        current_opponent="AG2",
        active_agent="AG1",
        debate_stage="ag1_main_thread",
        integrated_rules=[INTEGRATED_RULE],
        history=[ARG_A, ARG_B],
        dialogue_history=[ARG_A.to_dialogue_dict(), ARG_B.to_dialogue_dict()],
    )


async def run(print_prompt: bool) -> None:
    state = build_state()

    if print_prompt:
        print("[prompt]")
        print(build_main_argument_prompt(state, "AG1"))
        print()

    for i in range(1, 11):
        update = await can_generate_main(build_state())
        arg = update.get("current_argument")
        print(f"[can_generate_main {i}/10]")
        print(json.dumps(
            {
                "argument": arg.payload if arg else None,
                "metadata": {
                    "id": arg.id,
                    "type": arg.type,
                    "agent": arg.agent,
                } if arg else None,
                "main_argument_available": update.get("main_argument_available"),
                "main_argument_unavailable_reason": update.get("main_argument_unavailable_reason"),
            },
            ensure_ascii=False,
            indent=2,
        ))
        print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--print-prompt", action="store_true", help="プロンプトも表示する")
    args = parser.parse_args()
    asyncio.run(run(args.print_prompt))
