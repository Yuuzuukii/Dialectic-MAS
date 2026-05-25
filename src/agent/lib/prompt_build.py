from __future__ import annotations

import json
from typing import Any

try:
    from ..schema.state import ArgumentRecord
    from ..schema.types import AgentName
    from .prompt import PromptTemplates
except ImportError:  # pragma: no cover - supports LangGraph file-path loading.
    from lib.prompt import PromptTemplates
    from schema.state import ArgumentRecord
    from schema.types import AgentName


def _main_argument_revision_context(state: Any, agent: AgentName) -> str:
    rules = getattr(state, "integrated_rules", [])
    if not rules:
        return ""
    previous = [
        arg for arg in state.history if arg.type == "main" and arg.agent == agent
    ]
    previous_payload = previous[-1].payload if previous else None

    lines = [
        "Revision Context:",
        "- Construct a new alternative main argument using the integrated rule.",
        "- Do not repeat a previous main argument with the same conclusion and substantially the same warrant.",
    ]
    if previous_payload is not None:
        lines.extend(
            [
                "Previous Main Argument:",
                json.dumps(previous_payload, ensure_ascii=False),
            ]
        )
    lines.append("Integrated Rules:")
    lines.extend(f"- {rule}" for rule in rules)
    return "\n".join(lines)


def _proponent_previous_moves_text(state: Any, agent: AgentName) -> str:
    if agent != state.current_proponent:
        return ""
    previous = [arg for arg in state.history if arg.agent == agent]
    if not previous:
        return ""
    lines = [
        "ProponentPreviousMoves in this dialogue branch:",
        (
            "Non-repetition rule: if you are the Proponent, do not repeat the "
            "same conclusion from the same or substantially same rules, premises, "
            "or warrant as any item below."
        ),
    ]
    for arg in previous:
        lines.append(
            json.dumps(
                {
                    "id": arg.id,
                    "type": arg.type,
                    "attack": arg.attack,
                    "target_id": arg.target_id,
                    "rules": arg.body.get("rules", []),
                    "Conc": arg.conclusions,
                    "Ass": arg.assumptions,
                },
                ensure_ascii=False,
            )
        )
    return "\n\n" + "\n".join(lines) + "\n"


def build_main_argument_prompt(state: Any, agent: AgentName) -> str:
    return PromptTemplates.MAIN_ARGUMENT_AVAILABILITY.format(
        issue=state.question,
        revision_context=_main_argument_revision_context(state, agent),
    ).strip()


def build_attack_prompt(
    state: Any,
    attacker: AgentName,
    target: ArgumentRecord,
    *,
    purpose: str,
) -> str:
    template = (
        PromptTemplates.COUNTER_ARGUMENT
        if purpose == "defend_main"
        else PromptTemplates.DEFEATING_ARGUMENT
    )
    return (
        f"Purpose: {purpose}\n"
        f"Target argument id: {target.id}\n"
        f"Target argument:\n{target.argument}\n\n"
        f"{_proponent_previous_moves_text(state, attacker)}"
        f"{template}"
    )


def build_undercut_prompt(state: Any, attacker: AgentName, target: ArgumentRecord) -> str:
    return (
        f"Target argument id: {target.id}\n"
        f"Target argument:\n{target.argument}\n\n"
        f"{_proponent_previous_moves_text(state, attacker)}"
        f"{PromptTemplates.UNDERCUT_CHECK}"
    )


def build_generalization_prompt(warrant_result: str) -> str:
    return f"{warrant_result}\n{PromptTemplates.GENERALIZATION}"


def build_integration_prompt(warrant_result: str, generalization_result: str) -> str:
    return (
        f"{warrant_result}\n\n"
        f"{generalization_result}"
        f"{PromptTemplates.INTEGRATION}"
    )
