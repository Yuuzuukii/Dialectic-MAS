from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.agent.graphs.dialectic_workflow import State
from src.agent.graphs.nodes import main_argument_prompt, p_main, thread_finding
from src.agent.schema.outputs.schema import ArgumentRecord

def_module = importlib.import_module("def")
AG1_STANCE = def_module.AG1_STANCE
AG2_STANCE = def_module.AG2_STANCE
QUESTION = def_module.QUESTION
_jsonable = def_module._jsonable
_record_argument_payload = def_module._record_argument_payload


FIRST_MAIN_ARGUMENT = {
    "Argument": {
        "rules": [
            {
                "id": "r1",
                "antecedent": {
                    "strong": ["a is compact", "a is light"],
                    "weak_negation": [],
                },
                "consequent": "We should buy camera a.",
            }
        ],
        "Conc": ["We should buy camera a."],
        "Ass": [],
    }
}


FIRST_REBUTTAL = {
    "can_defeat": "YES",
    "Argument": {
        "rules": [
            {
                "id": "r1",
                "antecedent": {
                    "strong": ["a is out of stock"],
                    "weak_negation": [],
                },
                "consequent": "We should not buy camera a.",
            }
        ],
        "Conc": ["We should not buy camera a."],
        "Ass": [],
        "attack": "rebut",
        "target": {
            "argument_id": "arg-0b5d1ae606",
            "field": "Conc",
            "statement": "We should buy camera a.",
        },
    },
}


def json_text(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run only AG1's second-round p_main node.")
    parser.add_argument("--question", default=QUESTION)
    parser.add_argument("--agent1-stance", default=AG1_STANCE)
    parser.add_argument("--agent2-stance", default=AG2_STANCE)
    parser.add_argument(
        "--integrated-rule",
        action="append",
        default=[],
        help="Integrated rule to pass into round 2. Can be repeated.",
    )
    parser.add_argument(
        "--additional-context",
        default="{}",
        help="JSON string for State.additional_context.",
    )
    parser.add_argument(
        "--print-prompt",
        action="store_true",
        help="Print the exact p_main prompt before invoking the LLM.",
    )
    return parser


async def run() -> None:
    args = build_parser().parse_args()

    first_main = ArgumentRecord(
        id="arg-0b5d1ae606",
        type="main",
        argument=json_text(FIRST_MAIN_ARGUMENT),
        support=[],
        agent="AG1",
    )
    first_rebuttal = ArgumentRecord(
        type="defeat",
        argument=json_text(FIRST_REBUTTAL),
        support=[],
        agent="AG2",
        target_id="arg-0b5d1ae606",
        attack="rebut",
    )

    base_state = State(
        question=args.question,
        agent1_stance=args.agent1_stance,
        agent2_stance=args.agent2_stance,
        additional_context=json.loads(args.additional_context),
        current_proponent="AG1",
        current_opponent="AG2",
        active_agent="AG1",
        debate_stage="ag1_main_thread",
        history=[first_main, first_rebuttal],
        dialogue_history=[first_main.to_dialogue_dict(), first_rebuttal.to_dialogue_dict()],
        current_argument=first_main,
        b_argument=first_rebuttal,
    )
    finding = thread_finding(base_state, "overruled")

    state = State(
        question=args.question,
        agent1_stance=args.agent1_stance,
        agent2_stance=args.agent2_stance,
        additional_context=json.loads(args.additional_context),
        debate_round=2,
        current_proponent="AG1",
        current_opponent="AG2",
        active_agent="AG1",
        debate_stage="ag1_main_thread",
        integrated_rules=args.integrated_rule,
        learned_findings=[finding] if finding else [],
        history=[first_main, first_rebuttal],
        dialogue_history=[first_main.to_dialogue_dict(), first_rebuttal.to_dialogue_dict()],
    )

    if args.print_prompt:
        print("[second_round_p_main_prompt]")
        print(main_argument_prompt(state, "AG1"))
        print()

    update = await p_main(state)
    payload = _record_argument_payload(update.get("current_argument"))

    print("[second_round_p_main]")
    print(json.dumps(_jsonable(payload), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(run())
