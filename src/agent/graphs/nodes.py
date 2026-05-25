from __future__ import annotations

import json
import os
from typing import Any

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage

try:
    from ..lib.llm import call_llm_messages_structured
    from ..lib.prompt_build import (
        build_attack_prompt,
        build_generalization_prompt,
        build_integration_prompt,
        build_main_argument_prompt,
        build_undercut_prompt,
    )
    from ..schema.outputs.llm import (
        DefeatingArgumentOutput,
        GeneralizationOutput,
        IntegrationOutput,
        MainArgumentAvailabilityOutput,
        UndercutOutput,
    )
    from ..schema.state import ArgumentRecord, parse_serialized_payload
    from ..schema.types import AgentName
    from .defeat_workflow import (
        find_attack,
        run_defeat_subgraph,
        run_strict_defeat_subgraph,
    )
except ImportError:  # pragma: no cover - supports LangGraph file-path loading.
    from graphs.defeat_workflow import (
        find_attack,
        run_defeat_subgraph,
        run_strict_defeat_subgraph,
    )
    from lib.llm import call_llm_messages_structured
    from lib.prompt_build import (
        build_attack_prompt,
        build_generalization_prompt,
        build_integration_prompt,
        build_main_argument_prompt,
        build_undercut_prompt,
    )
    from schema.outputs.llm import (
        DefeatingArgumentOutput,
        GeneralizationOutput,
        IntegrationOutput,
        MainArgumentAvailabilityOutput,
        UndercutOutput,
    )
    from schema.state import ArgumentRecord, parse_serialized_payload
    from schema.types import AgentName

load_dotenv()

MODEL = os.getenv("MODEL", "gpt-5-mini")


def agent_stance(state: Any, agent: AgentName) -> str:
    return state.agent1_stance if agent == "AG1" else state.agent2_stance


def dialogue_history(history: list[ArgumentRecord]) -> list[dict[str, Any]]:
    return [arg.to_dialogue_dict() for arg in history]

async def invoke_agent_structured(system_prompt: str, human_prompt: str, schema: type[Any]) -> Any:
    return await call_llm_messages_structured(
        [SystemMessage(content=system_prompt), HumanMessage(content=human_prompt)],
        schema,
        MODEL,
    )

# Conc, Assを付け足す関数
def argument_body_json(argument: Any) -> str:
    body = argument.model_dump(exclude_none=True)
    rules = body.get("rules", [])
    conc_items: list[str] = []
    ass_items: list[str] = []
    if isinstance(rules, list):
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            consequent = rule.get("consequent")
            if isinstance(consequent, str) and consequent.strip():
                conc_items.append(consequent.strip())
            antecedent = rule.get("antecedent", {})
            if not isinstance(antecedent, dict):
                continue
            weak_negation = antecedent.get("weak_negation", [])
            if isinstance(weak_negation, list):
                ass_items.extend(
                    item.strip()
                    for item in weak_negation
                    if isinstance(item, str) and item.strip()
                )
    body["Conc"] = conc_items
    body["Ass"] = ass_items
    return json.dumps({"Argument": body}, ensure_ascii=False, indent=2)


def thread_finding(state: Any, status: str) -> str | None:
    if state.current_argument is None or state.b_argument is None:
        return None
    main_conc = "; ".join(state.current_argument.conclusions) or "the previous main argument"
    defeat_conc = "; ".join(state.b_argument.conclusions) or "the defeating argument"
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

# 反論生成
async def generate_attack(
    state: Any,
    attacker: AgentName,
    target: ArgumentRecord,
    *,
    purpose: str,
) -> ArgumentRecord | None:
    prompt = build_attack_prompt(state, attacker, target, purpose=purpose)
    output = await invoke_agent_structured(agent_stance(state, attacker), prompt, DefeatingArgumentOutput)
    if output.can_defeat != "YES" or output.Argument is None or output.Attack is None:
        return None
    response = argument_body_json(output.Argument)
    generated = ArgumentRecord(
        type="counter" if purpose == "defend_main" else "defeat",
        argument=response,
        support=[],
        agent=attacker,
        attack=output.Attack.method,
        target_id=target.id,
        target_field=output.Attack.target.field,
        target_statement=output.Attack.target.statement,
    )
    if find_attack(generated, target) is None:
        return None
    return generated

# undercut生成
async def generate_undercut(
    state: Any,
    attacker: AgentName,
    target: ArgumentRecord,
) -> ArgumentRecord | None:
    if not target.assumptions:
        return None
    prompt = build_undercut_prompt(state, attacker, target)
    output = await invoke_agent_structured(agent_stance(state, attacker), prompt, UndercutOutput)
    if output.can_undercut != "YES" or output.Argument is None:
        return None
    response = argument_body_json(output.Argument)
    generated = ArgumentRecord(
        type="defeat",
        argument=response,
        support=[],
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


def complete_thread(state: Any, status: str, extra_history: list[ArgumentRecord] | None = None) -> dict[str, Any]:
    key = "ag1" if state.current_proponent == "AG1" else "ag2"
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


# 主張ノード
async def can_generate_main(state: Any) -> dict[str, Any]:
    agent = state.current_proponent
    prompt = build_main_argument_prompt(state, agent)
    output = await invoke_agent_structured(
        agent_stance(state, agent),
        prompt,
        MainArgumentAvailabilityOutput,
    )
    can_generate = output.can_generate == "YES"
    update: dict[str, Any] = {
        "main_argument_available": can_generate,
        "main_argument_unavailable_reason": None if can_generate else output.reason,
    }
    if not can_generate:
        update["justification_status"] = "no_new_main_argument"
        return update

    if output.Argument is None:
        return {
            "error": "Main argument availability was YES but no Argument was generated.",
            "main_argument_available": False,
            "main_argument_unavailable_reason": output.reason,
        }

    response = argument_body_json(output.Argument)
    argument = ArgumentRecord(type="main", argument=response, support=[], agent=agent)
    history = [*state.history, argument]
    update.update(
        {
            "active_agent": "AG2" if agent == "AG1" else "AG1",
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
    )
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

# 反論ノード
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
        return complete_thread(state, "justified")
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

# defeat確認ノード
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
        update = complete_thread(
            state,
            "justified",
            [result.blocker] if result.blocker is not None else None,
        )
        if result.blocker is not None:
            update["last_generated_argument"] = result.blocker
        update["defeat_relations"] = relations
        update["last_can_defeat"] = False
        return update
    return {"defeat_relations": relations, "last_can_defeat": True, "b_defeats_a": True}

# 主張を守るためのカウンターノード
async def p_counter_b(state: Any) -> dict[str, Any]:
    if state.b_argument is None:
        return {"error": "No B argument to counter."}
    argument = await generate_attack(
        state,
        state.current_proponent,
        state.b_argument,
        purpose="defend_main",
    )
    if argument is None:
        return complete_thread(state, "overruled")
    history = [*state.history, argument]
    return {
        "active_agent": state.current_opponent,
        "c_argument": argument,
        "c_argument_id": argument.id,
        "last_generated_argument": argument,
        "history": history,
        "dialogue_history": dialogue_history(history),
    }

# カウンターのdefeat確認ノード
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
        update = complete_thread(
            state,
            "overruled",
            [result.blocker] if result.blocker is not None else None,
        )
        if result.blocker is not None:
            update["last_generated_argument"] = result.blocker
        update["defeat_relations"] = relations
        update["last_can_defeat"] = False
        return update
    return {"defeat_relations": relations, "last_can_defeat": True, "c_defeats_b": True}

# カウンターのstrictly defeat確認ノード
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
        update = complete_thread(state, "justified")
        update["b_defeats_c"] = False
        update["c_strictly_defeats_b"] = True
    else:
        update = complete_thread(state, "defensible")
        update["b_defeats_c"] = True
        update["c_strictly_defeats_b"] = False
    update["defeat_relations"] = relations
    return update

# warrant抽出ノード
async def extract_warrants(state: Any) -> dict[str, Any]:
    if state.ag1_main_argument is None or state.ag2_main_argument is None:
        return {"error": "AG1またはAG2のmain argumentが見つかりません"}
    try:
        ag1_last_rule = state.ag1_main_argument.body.get("rules", [])[-1]
        ag2_last_rule = state.ag2_main_argument.body.get("rules", [])[-1]
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

# 汎化ノード
async def generalize(state: Any) -> dict[str, Any]:
    if state.warrant_result is None:
        return {"error": "Cannot generalize without warrants."}
    output = await invoke_agent_structured(
        state.agent1_stance,
        build_generalization_prompt(state.warrant_result),
        GeneralizationOutput,
    )
    response = json.dumps(output.model_dump(exclude_none=True), ensure_ascii=False, indent=2)
    return {"generalization_result": response}

# 統合ノード
async def integrate(state: Any) -> dict[str, Any]:
    if state.warrant_result is None or state.generalization_result is None:
        return {"error": "Cannot integrate without warrants and generalization."}
    output = await invoke_agent_structured(
        state.agent1_stance,
        build_integration_prompt(state.warrant_result, state.generalization_result),
        IntegrationOutput,
    )
    response = json.dumps(output.model_dump(exclude_none=True), ensure_ascii=False, indent=2)
    rule = extract_integrated_rule(response)
    if rule is None:
        return {"error": "統合結果から新しいルールを抽出できませんでした"}
    return {"integration_result": response, "integrated_rule": rule}

# 合意核構築ノード
def extract_integrated_rule(integration_result: str) -> str | None:
    data = parse_serialized_payload(integration_result)
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
        "main_argument_available": state.main_argument_available,
        "main_argument_unavailable_reason": state.main_argument_unavailable_reason,
        "ag1_thread_status": state.ag1_thread_status,
        "ag2_thread_status": state.ag2_thread_status,
        "agent1_stance": state.agent1_stance,
        "agent2_stance": state.agent2_stance,
    }


async def finish_with_error(state: Any) -> dict[str, Any]:
    result = await finish(state)
    result["error"] = state.error
    return result
