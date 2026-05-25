from __future__ import annotations

from typing import Any

try:
    from ..graphs.defeat_workflow import find_attack
    from ..schema.outputs.llm import DefeatingArgumentOutput, UndercutOutput
    from ..schema.state import ArgumentRecord
    from ..schema.types import AgentName
    from .llm import invoke_agent_structured
    from .prompt_build import build_attack_prompt, build_undercut_prompt
except ImportError:  # pragma: no cover - supports LangGraph file-path loading.
    from graphs.defeat_workflow import find_attack
    from lib.llm import invoke_agent_structured
    from lib.prompt_build import build_attack_prompt, build_undercut_prompt
    from schema.outputs.llm import DefeatingArgumentOutput, UndercutOutput
    from schema.state import ArgumentRecord
    from schema.types import AgentName


def _stance(state: Any, agent: AgentName) -> str:
    return state.agent1_stance if agent == "AG1" else state.agent2_stance


async def generate_attack(
    state: Any,
    attacker: AgentName,
    target: ArgumentRecord,
    *,
    purpose: str,
) -> ArgumentRecord | None:
    output = await invoke_agent_structured(
        _stance(state, attacker),
        build_attack_prompt(state, attacker, target, purpose=purpose),
        DefeatingArgumentOutput,
    )
    if output.can_defeat != "YES" or output.Argument is None or output.Attack is None:
        return None

    generated = ArgumentRecord.from_generated_body(
        output.Argument,
        type="counter" if purpose == "defend_main" else "defeat",
        agent=attacker,
        attack=output.Attack.method,
        target_id=target.id,
        target_field=output.Attack.target.field,
        target_statement=output.Attack.target.statement,
    )
    return generated if find_attack(generated, target) is not None else None


async def generate_undercut(
    state: Any,
    attacker: AgentName,
    target: ArgumentRecord,
) -> ArgumentRecord | None:
    if not target.assumptions:
        return None
    output = await invoke_agent_structured(
        _stance(state, attacker),
        build_undercut_prompt(state, attacker, target),
        UndercutOutput,
    )
    if output.can_undercut != "YES" or output.Argument is None:
        return None

    generated = ArgumentRecord.from_generated_body(
        output.Argument,
        type="defeat",
        agent=attacker,
        attack="undercut",
        target_id=target.id,
    )
    match = find_attack(generated, target)
    if match is None:
        return None
    generated.target_field = match.field
    generated.target_statement = match.statement
    return generated
