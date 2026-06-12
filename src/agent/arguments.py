"""Argument generation, serialization, and stance helpers."""

from __future__ import annotations

import json
from typing import Any

try:
    from .llm import invoke_agent_structured_messages
    from .prompt_builders import build_attack_messages, build_undercut_messages
    from .schema.llm_outputs import (
        ArgumentBody,
        DefeatingArgumentOutput,
        UndercutOutput,
    )
    from .schema.state import ArgumentRecord
    from .schema.types import AgentName
except ImportError:  # pragma: no cover - supports LangGraph file-path loading.
    from llm import invoke_agent_structured_messages
    from prompt_builders import build_attack_messages, build_undercut_messages
    from schema.llm_outputs import ArgumentBody, DefeatingArgumentOutput, UndercutOutput
    from schema.state import ArgumentRecord
    from schema.types import AgentName


def agent_stance(state: Any, agent: AgentName) -> str:
    return state.agent1_stance if agent == "AG1" else state.agent2_stance


def argument_body_json(argument: ArgumentBody) -> str:
    """Serialize an ArgumentBody with Conc and Ass derived from its rules."""
    body = argument.model_dump(exclude_none=True)
    rules = body.get("rules", [])
    conclusions: list[str] = []
    assumptions: list[str] = []
    if isinstance(rules, list):
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            consequent = rule.get("consequent")
            if isinstance(consequent, str) and consequent.strip():
                conclusions.append(consequent.strip())
            antecedent = rule.get("antecedent", {})
            if isinstance(antecedent, dict):
                for item in antecedent.get("weak_negation", []) or []:
                    if isinstance(item, str) and item.strip():
                        assumptions.append(item.strip())
    body["Conc"] = conclusions
    body["Ass"] = assumptions
    return json.dumps({"Argument": body}, ensure_ascii=False, indent=2)


async def generate_attack(
    state: Any,
    attacker: AgentName,
    target: ArgumentRecord,
    *,
    purpose: str,
) -> ArgumentRecord | None:
    messages = build_attack_messages(state, attacker, target, purpose=purpose)
    output = await invoke_agent_structured_messages(messages, DefeatingArgumentOutput)
    if output.can_defeat != "YES" or output.Argument is None or output.Attack is None:
        return None
    return ArgumentRecord(
        type="counter" if purpose == "defend_main" else "defeat",
        argument=argument_body_json(output.Argument),
        support=[],
        agent=attacker,
        attack=output.Attack.method,
        target_id=target.id,
        target_field=output.Attack.target.field,
        target_statement=output.Attack.target.statement,
        round=getattr(state, "debate_round", 1),
    )


async def generate_undercut(
    state: Any,
    attacker: AgentName,
    target: ArgumentRecord,
) -> ArgumentRecord | None:
    if not target.assumptions:
        return None
    messages = build_undercut_messages(state, attacker, target)
    output = await invoke_agent_structured_messages(messages, UndercutOutput)
    if output.can_undercut != "YES" or output.Argument is None:
        return None
    return ArgumentRecord(
        type="defeat",
        argument=argument_body_json(output.Argument),
        support=[],
        agent=attacker,
        attack="undercut",
        target_id=target.id,
        target_field="Ass",
        round=getattr(state, "debate_round", 1),
    )
