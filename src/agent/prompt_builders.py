from __future__ import annotations

import json
from typing import Any

try:
    from .prompts import PromptTemplates
    from .schema.state import ArgumentRecord
    from .schema.types import AgentName
except ImportError:  # pragma: no cover - supports LangGraph file-path loading.
    from prompts import PromptTemplates
    from schema.state import ArgumentRecord
    from schema.types import AgentName


def _main_argument_revision_context(state: Any, agent: AgentName) -> str:
    rules = getattr(state, "integrated_rules", [])
    if not rules:
        return ""
    previous_mains = [
        arg for arg in state.history if arg.type == "main" and arg.agent == agent
    ]
    previous = previous_mains[-1] if previous_mains else None

    lines = [
        "Revision Context:",
        "You have been in a debate, but your previous argument was not accepted — it was defeated by your opponent.",
        "However, through the exchange, both parties have identified shared criteria that neither side can deny.",
        "These are now given to you as integrated rules.",
        "Your task is to propose a new argument built on these integrated rules.",
        "- Your new argument must be different from the previous one: do not reuse the same conclusion or the same reasoning.",
        "- Your new argument must not be vulnerable to the same attacks that defeated the previous one.",
        "- Ground your argument in the integrated rules as much as possible.",
    ]
    if previous is not None:
        lines.extend(["Previous Main Argument (defeated — do not repeat):", json.dumps(previous.payload, ensure_ascii=False)])
        attacks = [arg for arg in state.history if arg.target_id == previous.id]
        if attacks:
            lines.append("Arguments that defeated your previous argument (do not make the same mistake):")
            for atk in attacks:
                lines.append(json.dumps(
                    {
                        "attack": atk.attack,
                        "target_statement": atk.target_statement,
                        "rules": atk.body.get("rules", []),
                        "Conc": atk.conclusions,
                        "Ass": atk.assumptions,
                    },
                    ensure_ascii=False,
                ))
    lines.append("Integrated Rules (use these as the basis of your new argument):")
    lines.extend(f"- {rule}" for rule in rules)
    return "\n".join(lines)


def _proponent_previous_moves_text(state: Any, agent: AgentName) -> str:
    if agent != state.current_proponent:
        return ""
    previous = [arg for arg in state.history if arg.agent == agent]
    if not previous:
        return ""
    lines = [
        "Your previous arguments in this dialogue branch:",
        (
            "Non-repetition rule: do not repeat the same conclusion from the same "
            "or substantially same rules, premises, or warrant as any item below."
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


def build_generalization_prompt(warrant_result: str, conversation_history: str) -> str:
    return (
        f"## Warrants\n{warrant_result}\n\n"
        f"## Dialogue History\n{conversation_history}\n"
        f"{PromptTemplates.GENERALIZATION}"
    )


def build_integration_prompt(warrant_result: str, generalization_result: str) -> str:
    return (
        f"{warrant_result}\n\n"
        f"{generalization_result}"
        f"{PromptTemplates.INTEGRATION}"
    )
