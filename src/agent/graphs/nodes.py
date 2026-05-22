from __future__ import annotations

import json
import os
from typing import Any

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage

try:
    from ..lib.llm import call_llm_messages_structured
    from ..lib.prompt import PromptTemplates
    from ..schema.outputs.schema import (
        AgentName,
        ArgumentRecord,
        AttackType,
        DefeatingArgumentOutput,
        GeneralizationOutput,
        IntegrationOutput,
        MainArgumentOutput,
        UndercutOutput,
    )
    from .defeat_workflow import (
        ass,
        conc,
        run_defeat_subgraph,
        run_strict_defeat_subgraph,
        valid_declared_attack,
    )
except ImportError:  # pragma: no cover - supports LangGraph file-path loading.
    from graphs.defeat_workflow import (
        ass,
        conc,
        run_defeat_subgraph,
        run_strict_defeat_subgraph,
        valid_declared_attack,
    )
    from lib.llm import call_llm_messages_structured
    from lib.prompt import PromptTemplates
    from schema.outputs.schema import (
        AgentName,
        ArgumentRecord,
        AttackType,
        DefeatingArgumentOutput,
        GeneralizationOutput,
        IntegrationOutput,
        MainArgumentOutput,
        UndercutOutput,
    )

load_dotenv()

MODEL = os.getenv("MODEL", "gpt-5-mini")


def opponent(agent: AgentName) -> AgentName:
    return "AG2" if agent == "AG1" else "AG1"


def agent_stance(state: Any, agent: AgentName) -> str:
    return state.agent1_stance if agent == "AG1" else state.agent2_stance


def dialogue_history(history: list[ArgumentRecord]) -> list[dict[str, Any]]:
    return [arg.to_dialogue_dict() for arg in history]


def extract_json_from_argument(argument_text: str | None) -> dict[str, Any]:
    if not argument_text:
        return {}
    try:
        if "```json" in argument_text:
            json_start = argument_text.find("```json") + 7
            json_end = argument_text.find("```", json_start)
            json_str = argument_text[json_start:json_end].strip()
        elif "```" in argument_text:
            json_start = argument_text.find("```") + 3
            json_end = argument_text.find("```", json_start)
            json_str = argument_text[json_start:json_end].strip()
        else:
            json_start = argument_text.find("{")
            json_end = argument_text.rfind("}") + 1
            json_str = argument_text[json_start:json_end].strip()
        return json.loads(json_str)
    except Exception:
        return {}


def argument_payload(record: ArgumentRecord | None) -> dict[str, Any]:
    if record is None:
        return {}
    return extract_json_from_argument(record.argument)


def record(
    agent: AgentName,
    arg_type: str,
    content: str,
    *,
    attack: AttackType | None = None,
    target_id: str | None = None,
    status: str | None = None,
) -> ArgumentRecord:
    return ArgumentRecord(
        type=arg_type,  # type: ignore[arg-type]
        argument=content,
        support=[],
        agent=agent,
        attack=attack,
        target_id=target_id,
        status=status,  # type: ignore[arg-type]
    )


def background_knowledge_text(state: Any) -> str:
    # Optional facts supplied by CLI/API via State.additional_context.
    # Empty in the default def.py example, but useful for product facts or task constraints.
    if not state.additional_context:
        return ""
    return (
        "\n\nBackgroundKnowledge:\n"
        f"{json.dumps(state.additional_context, ensure_ascii=False, indent=2)}"
    )


def integrated_rules_text(state: Any) -> str:
    rules = getattr(state, "integrated_rules", [])
    if not rules:
        return ""
    formatted = "\n".join(f"- {rule}" for rule in rules)
    return (
        "\n\nIntegratedRules for this round:\n"
        "Use these as reusable rules, not as evidence for concrete facts.\n"
        f"{formatted}\n"
    )


def previous_main_arguments_context(state: Any, agent: AgentName) -> str:
    previous = [arg for arg in state.history if arg.type == "main" and arg.agent == agent]
    if not previous:
        return ""
    lines = [
        "Your previous main arguments:",
        "Use these only to avoid repeating your own previous main argument.",
        "Do not treat another agent's premises as facts in your own main argument.",
    ]
    for arg in previous:
        payload = argument_payload(arg)
        body = payload.get("Argument", {}) if isinstance(payload, dict) else {}
        conc_items = body.get("Conc", []) if isinstance(body, dict) else []
        rules = body.get("rules", []) if isinstance(body, dict) else []
        last_rule = rules[-1] if isinstance(rules, list) and rules else {}
        warrant = last_rule.get("antecedent", {}) if isinstance(last_rule, dict) else {}
        lines.append(
            json.dumps(
                {
                    "agent": arg.agent,
                    "id": arg.id,
                    "Conc": conc_items,
                    "last_warrant": warrant,
                    "last_consequent": last_rule.get("consequent") if isinstance(last_rule, dict) else None,
                },
                ensure_ascii=False,
            )
        )
    return "\n\n" + "\n".join(lines) + "\n"


def proponent_previous_moves_text(state: Any, agent: AgentName) -> str:
    if agent != state.current_proponent:
        return ""
    previous = [arg for arg in state.history if arg.agent == agent]
    if not previous:
        return ""
    lines = [
        "ProponentPreviousMoves in this dialogue branch:",
        "Non-repetition rule: if you are the Proponent, do not repeat the same move/content as any item below.",
    ]
    for arg in previous:
        payload = argument_payload(arg)
        body = payload.get("Argument", {}) if isinstance(payload, dict) else {}
        lines.append(
            json.dumps(
                {
                    "id": arg.id,
                    "type": arg.type,
                    "attack": arg.attack,
                    "target_id": arg.target_id,
                    "Conc": body.get("Conc", []) if isinstance(body, dict) else [],
                    "Ass": body.get("Ass", []) if isinstance(body, dict) else [],
                },
                ensure_ascii=False,
            )
        )
    return "\n\n" + "\n".join(lines) + "\n"


def learned_findings_text(state: Any, agent: AgentName) -> str:
    if not state.learned_findings:
        return ""
    parts = [f"\n\n{PromptTemplates.LEARNED_FINDINGS.strip()}"]
    findings = "\n".join(f"- {finding}" for finding in state.learned_findings)
    parts.append(f"LearnedFindings:\n{findings}")
    return "\n".join(parts) + "\n"


def main_argument_prompt(state: Any, agent: AgentName) -> str:
    return (
        f"{PromptTemplates.MAIN_ARGUMENT}\n\n"
        f"Issue: {state.question}"
        f"\nDebateRound: {state.debate_round}"
        f"\nCurrentProponent: {agent}"
        f"{integrated_rules_text(state)}"
        f"{learned_findings_text(state, agent)}"
        f"{background_knowledge_text(state)}"
        f"{previous_main_arguments_context(state, agent)}"
        "\nFinal instruction: generate a new main argument that does not violate ForbiddenMainArguments."
    )


async def invoke_agent_structured(system_prompt: str, human_prompt: str, schema: type[Any]) -> Any:
    return await call_llm_messages_structured(
        [SystemMessage(content=system_prompt), HumanMessage(content=human_prompt)],
        schema,
        MODEL,
    )


def structured_json(output: Any) -> str:
    return json.dumps(output.model_dump(exclude_none=True), ensure_ascii=False, indent=2)


def argument_body_json(argument: Any) -> str:
    return json.dumps({"Argument": argument.model_dump(exclude_none=True)}, ensure_ascii=False, indent=2)


def thread_finding(state: Any, status: str) -> str | None:
    if state.current_argument is None or state.b_argument is None:
        return None
    main_conc = "; ".join(conc(state.current_argument)) or "the previous main argument"
    defeat_conc = "; ".join(conc(state.b_argument)) or "the defeating argument"
    if status == "overruled":
        return (
            f"{state.current_proponent}'s previous main argument ({main_conc}) was overruled by "
            f"{state.current_opponent}'s {state.b_argument.attack} ({defeat_conc}). "
            "Do not repeat the same main argument unless this defeating reason is resolved."
        )
    if status == "defensible":
        return (
            f"{state.current_proponent}'s previous main argument ({main_conc}) remained defensible, "
            f"with an unresolved conflict against {state.current_opponent}'s {state.b_argument.attack} ({defeat_conc}). "
            "Do not repeat the same main argument as if the conflict were resolved."
        )
    return None


async def generate_attack(
    state: Any,
    attacker: AgentName,
    target: ArgumentRecord,
    *,
    purpose: str,
    prompt_template: str | None = None,
) -> ArgumentRecord | None:
    prompt = (
        f"Purpose: {purpose}\n"
        f"Target argument id: {target.id}\n"
        f"Target argument:\n{target.argument}\n\n"
        f"{proponent_previous_moves_text(state, attacker)}"
        f"{prompt_template or PromptTemplates.DEFEATING_ARGUMENT}"
        f"{background_knowledge_text(state)}"
    )
    output = await invoke_agent_structured(agent_stance(state, attacker), prompt, DefeatingArgumentOutput)
    if output.can_defeat != "YES" or output.Argument is None or output.Attack is None:
        return None
    response = argument_body_json(output.Argument)
    attack = output.Attack.attack
    generated = record(
        attacker,
        "counter" if purpose == "defend_main" else "defeat",
        response,
        attack=attack,
        target_id=output.Attack.target.argument_id or target.id,
    )
    if generated.target_id != target.id:
        generated.target_id = target.id
    if not valid_declared_attack(generated, target):
        return None
    return generated


async def generate_undercut(
    state: Any,
    attacker: AgentName,
    target: ArgumentRecord,
) -> ArgumentRecord | None:
    if not ass(target):
        return None
    prompt = (
        f"Target argument id: {target.id}\n"
        f"Target argument:\n{target.argument}\n\n"
        f"{proponent_previous_moves_text(state, attacker)}"
        f"{PromptTemplates.UNDERCUT_CHECK}"
        f"{background_knowledge_text(state)}"
    )
    output = await invoke_agent_structured(agent_stance(state, attacker), prompt, UndercutOutput)
    if output.can_undercut != "YES" or output.Argument is None or output.Attack is None:
        return None
    response = argument_body_json(output.Argument)
    generated = record(
        attacker,
        "defeat",
        response,
        attack="undercut",
        target_id=output.Attack.target.argument_id or target.id,
    )
    if generated.target_id != target.id:
        generated.target_id = target.id
    if not valid_declared_attack(generated, target):
        return None
    return generated


def current_agent_thread_key(state: Any) -> str:
    return "ag1" if state.current_proponent == "AG1" else "ag2"


def status_update(state: Any, status: str, extra_history: list[ArgumentRecord] | None = None) -> dict[str, Any]:
    key = current_agent_thread_key(state)
    history = [*state.history]
    if extra_history:
        history.extend(extra_history)

    update: dict[str, Any] = {
        "current_thread_status": status,
        "history": history,
        "dialogue_history": dialogue_history(history),
    }
    finding = thread_finding(state, status)
    if finding is not None:
        learned_findings = [*state.learned_findings]
        if finding not in learned_findings:
            learned_findings.append(finding)
        update["learned_findings"] = learned_findings
    if key == "ag1":
        update["ag1_thread_status"] = status
    else:
        update["ag2_thread_status"] = status

    if status == "justified":
        update["justified_argument"] = state.current_argument.argument if state.current_argument else None
        update["justification_status"] = f"{key}_main_justified"
    elif status == "overruled":
        update["justification_status"] = f"{key}_main_overruled"

    if status in {"defensible", "overruled"}:
        if key == "ag1" and state.ag2_thread_status is None:
            update["current_proponent"] = "AG2"
            update["current_opponent"] = "AG1"
            update["active_agent"] = "AG2"
            update["current_argument"] = None
            update["b_argument"] = None
            update["c_argument"] = None
            update["d_argument"] = None
            update["b_argument_id"] = None
            update["c_argument_id"] = None
            update["d_argument_id"] = None
            update["b_defeats_a"] = None
            update["c_defeats_b"] = None
            update["b_defeats_c"] = None
            update["c_strictly_defeats_b"] = None
            update["debate_stage"] = "ag2_main_thread"
        else:
            update["current_proponent"] = state.current_proponent
            update["current_opponent"] = state.current_opponent
    return update


async def initialize(state: Any) -> dict[str, Any]:
    return {
        "turn_count": 0,
        "active_agent": "AG1",
        "current_proponent": "AG1",
        "current_opponent": "AG2",
        "debate_stage": "ag1_main_thread",
        "debate_round": 1,
        "learned_findings": [],
        "integrated_rules": [],
        "history": [],
        "current_argument": None,
        "ag1_main_argument": None,
        "ag2_main_argument": None,
        "ag1_thread_status": None,
        "ag2_thread_status": None,
        "current_thread_status": None,
        "b_argument": None,
        "c_argument": None,
        "d_argument": None,
        "b_argument_id": None,
        "c_argument_id": None,
        "d_argument_id": None,
        "b_defeats_a": None,
        "c_defeats_b": None,
        "b_defeats_c": None,
        "c_strictly_defeats_b": None,
        "defeat_relations": [],
        "warrant_result": None,
        "generalization_result": None,
        "integration_result": None,
        "integrated_rule": None,
        "justified_argument": None,
        "justification_status": None,
        "final_rebuttal": None,
        "dialogue_history": [],
        "error": None,
    }


async def p_main(state: Any) -> dict[str, Any]:
    agent = state.current_proponent
    prompt = main_argument_prompt(state, agent)
    output = await invoke_agent_structured(agent_stance(state, agent), prompt, MainArgumentOutput)
    if output.can_generate != "YES" or output.Argument is None:
        key = current_agent_thread_key(state)
        return {
            "current_argument": None,
            "current_thread_status": "no_main_argument",
            f"{key}_thread_status": "no_main_argument",
            "justification_status": f"{key}_main_not_generated",
        }
    response = structured_json(output)
    argument = record(agent, "main", response)
    history = [*state.history, argument]
    update: dict[str, Any] = {
        "active_agent": opponent(agent),
        "current_argument": argument,
        "current_thread_status": None,
        "b_argument": None,
        "c_argument": None,
        "d_argument": None,
        "b_argument_id": None,
        "c_argument_id": None,
        "d_argument_id": None,
        "b_defeats_a": None,
        "c_defeats_b": None,
        "b_defeats_c": None,
        "c_strictly_defeats_b": None,
        "history": history,
        "dialogue_history": dialogue_history(history),
    }
    if agent == "AG1":
        update.update(
            {
                "ag1_main_argument": argument,
                "ag1_current_main_id": argument.id,
                "ag1_thread_status": None,
                "debate_stage": "ag1_main_thread",
            }
        )
    else:
        update.update(
            {
                "ag2_main_argument": argument,
                "ag2_current_main_id": argument.id,
                "ag2_thread_status": None,
                "debate_stage": "ag2_main_thread",
            }
        )
    return update


async def o_defeat_a(state: Any) -> dict[str, Any]:
    if state.current_argument is None:
        return {"error": "No current main argument to attack."}
    argument = await generate_attack(
        state,
        state.current_opponent,
        state.current_argument,
        purpose="defeat_main",
    )
    if argument is None:
        return status_update(state, "justified")
    history = [*state.history, argument]
    return {
        "active_agent": state.current_proponent,
        "b_argument": argument,
        "b_argument_id": argument.id,
        "last_generated_argument": argument,
        "last_can_defeat": None,
        "history": history,
        "dialogue_history": dialogue_history(history),
    }


async def validate_b_defeats_a(state: Any) -> dict[str, Any]:
    if state.current_argument is None or state.b_argument is None:
        return {"error": "Cannot validate B defeats A without A and B."}
    result = await run_defeat_subgraph(
        state,
        state.b_argument,
        state.current_argument,
        state.current_proponent,
        relation_context="B defeats A",
        blocker_generator=generate_undercut,
    )
    relations = [*state.defeat_relations, *result.relations]
    if not result.defeats:
        update = status_update(
            state,
            "justified",
            [result.blocker] if result.blocker is not None else None,
        )
        update["defeat_relations"] = relations
        update["last_can_defeat"] = False
        return update
    return {"defeat_relations": relations, "last_can_defeat": True, "b_defeats_a": True}


async def p_counter_b(state: Any) -> dict[str, Any]:
    if state.b_argument is None:
        return {"error": "No B argument to counter."}
    argument = await generate_attack(
        state,
        state.current_proponent,
        state.b_argument,
        purpose="defend_main",
        prompt_template=PromptTemplates.COUNTER_ARGUMENT,
    )
    if argument is None:
        return status_update(state, "overruled")
    history = [*state.history, argument]
    return {
        "active_agent": state.current_opponent,
        "c_argument": argument,
        "c_argument_id": argument.id,
        "last_generated_argument": argument,
        "history": history,
        "dialogue_history": dialogue_history(history),
    }


async def validate_c_defeats_b(state: Any) -> dict[str, Any]:
    if state.b_argument is None or state.c_argument is None:
        return {"error": "Cannot validate C defeats B without B and C."}
    result = await run_defeat_subgraph(
        state,
        state.c_argument,
        state.b_argument,
        state.current_opponent,
        relation_context="C defeats B",
        blocker_generator=generate_undercut,
    )
    relations = [*state.defeat_relations, *result.relations]
    if not result.defeats:
        update = status_update(
            state,
            "overruled",
            [result.blocker] if result.blocker is not None else None,
        )
        update["defeat_relations"] = relations
        update["last_can_defeat"] = False
        return update
    return {"defeat_relations": relations, "last_can_defeat": True, "c_defeats_b": True}


async def validate_b_defeats_c(state: Any) -> dict[str, Any]:
    if state.b_argument is None or state.c_argument is None:
        return {"error": "Cannot validate B defeats C without B and C."}
    result = await run_strict_defeat_subgraph(
        state,
        state.c_argument,
        state.b_argument,
        forward_defender=state.current_opponent,
        reverse_defender=state.current_proponent,
        blocker_generator=generate_undercut,
        forward_already_true=True,
    )
    relations = [*state.defeat_relations]
    if result.forward is not None:
        relations.extend(result.forward.relations)
    if result.reverse is not None:
        relations.extend(result.reverse.relations)
    if result.strictly_defeats:
        update = status_update(state, "justified")
        update["b_defeats_c"] = False
        update["c_strictly_defeats_b"] = True
    else:
        update = status_update(state, "defensible")
        update["b_defeats_c"] = True
        update["c_strictly_defeats_b"] = False
    update["defeat_relations"] = relations
    return update


def extract_integrated_rule(integration_result: str) -> str | None:
    data = extract_json_from_argument(integration_result)
    argument = data.get("Argument", {})
    integration = argument.get("Integration", {}) if isinstance(argument, dict) else {}
    rule = integration.get("rule") if isinstance(integration, dict) else None
    if isinstance(rule, str) and rule.strip():
        normalized = " ".join(rule.lower().split())
        placeholder_phrases = (
            "concrete integrated conditions",
            "generalized conclusion",
            "integrated condition",
            "condition 1",
            "condition 2",
        )
        if any(phrase in normalized for phrase in placeholder_phrases):
            return None
        return rule.strip()
    return None


async def extract_warrants(state: Any) -> dict[str, Any]:
    if state.ag1_main_argument is None or state.ag2_main_argument is None:
        return {"error": "AG1またはAG2のmain argumentが見つかりません"}
    try:
        ag1_json = argument_payload(state.ag1_main_argument)
        ag2_json = argument_payload(state.ag2_main_argument)
        ag1_last_rule = ag1_json.get("Argument", {}).get("rules", [])[-1]
        ag2_last_rule = ag2_json.get("Argument", {}).get("rules", [])[-1]
        warrant_json = {
            "Argument1": {
                "warrant": {
                    "antecedent": {
                        "strong": ag1_last_rule["antecedent"].get("strong", []),
                        "weak_negation": ag1_last_rule["antecedent"].get("weak_negation", []),
                    },
                    "consequent": ag1_last_rule["consequent"],
                }
            },
            "Argument2": {
                "warrant": {
                    "antecedent": {
                        "strong": ag2_last_rule["antecedent"].get("strong", []),
                        "weak_negation": ag2_last_rule["antecedent"].get("weak_negation", []),
                    },
                    "consequent": ag2_last_rule["consequent"],
                }
            },
        }
        return {"warrant_result": json.dumps(warrant_json, ensure_ascii=False, indent=2)}
    except Exception as exc:
        return {"error": f"Warrant抽出中にエラーが発生しました: {exc}"}


async def generalize(state: Any) -> dict[str, Any]:
    if state.warrant_result is None:
        return {"error": "Cannot generalize without warrants."}
    output = await invoke_agent_structured(
        state.agent1_stance,
        f"{state.warrant_result}{background_knowledge_text(state)}\n\n{PromptTemplates.GENERALIZATION}",
        GeneralizationOutput,
    )
    response = structured_json(output)
    return {"generalization_result": response}


async def integrate(state: Any) -> dict[str, Any]:
    if state.warrant_result is None or state.generalization_result is None:
        return {"error": "Cannot integrate without warrants and generalization."}
    output = await invoke_agent_structured(
        state.agent1_stance,
        (
            f"{state.warrant_result}\n\n"
            f"{state.generalization_result}"
            f"{background_knowledge_text(state)}\n\n"
            f"{PromptTemplates.INTEGRATION}"
        ),
        IntegrationOutput,
    )
    response = structured_json(output)
    rule = extract_integrated_rule(response)
    if rule is None:
        return {"error": "統合結果から新しいルールを抽出できませんでした"}
    return {"integration_result": response, "integrated_rule": rule}


async def add_integrated_rule(state: Any) -> dict[str, Any]:
    if not state.integrated_rule:
        return {"error": "No integrated rule to add."}
    rules = [*state.integrated_rules]
    if state.integrated_rule not in rules:
        rules.append(state.integrated_rule)
    return {
        "debate_round": state.debate_round + 1,
        "integrated_rules": rules,
        "current_proponent": "AG1",
        "current_opponent": "AG2",
        "active_agent": "AG1",
        "debate_stage": "ag1_main_thread",
        "ag1_main_argument": None,
        "ag2_main_argument": None,
        "ag1_thread_status": None,
        "ag2_thread_status": None,
        "current_thread_status": None,
        "current_argument": None,
        "b_argument": None,
        "c_argument": None,
        "d_argument": None,
        "b_defeats_a": None,
        "c_defeats_b": None,
        "b_defeats_c": None,
        "c_strictly_defeats_b": None,
        "warrant_result": None,
        "generalization_result": None,
        "integration_result": None,
        "integrated_rule": None,
    }


async def route_after_thread_node(state: Any) -> dict[str, Any]:
    return {}


async def finish(state: Any) -> dict[str, Any]:
    return {
        "dialogue_history": dialogue_history(state.history),
        "justified_argument": state.justified_argument,
        "justification_status": state.justification_status,
        "final_rebuttal": state.final_rebuttal,
        "integrated_rules": state.integrated_rules,
        "debate_round": state.debate_round,
        "ag1_thread_status": state.ag1_thread_status,
        "ag2_thread_status": state.ag2_thread_status,
        "defeat_relations": state.defeat_relations,
        "agent1_stance": state.agent1_stance,
        "agent2_stance": state.agent2_stance,
    }


async def finish_with_error(state: Any) -> dict[str, Any]:
    result = await finish(state)
    result["error"] = state.error
    return result
