"""Graph node functions for the dialectical workflow."""

from __future__ import annotations

import json
from typing import Any

try:
    from .arguments import (
        argument_body_json,
        generate_attack,
        generate_undercut,
    )
    from .defeats import run_defeat_subgraph, run_strict_defeat_subgraph
    from .llm import (
        call_llm_messages,
        invoke_agent_structured,
        invoke_agent_structured_messages,
    )
    from .prompt_builders import (
        build_generalization_prompt,
        build_integration_prompt,
        build_main_argument_messages,
        compose_system,
    )
    from .prompts import PromptTemplates
    from .schema.llm_outputs import (
        GeneralizationOutput,
        IntegrationOutput,
        MainArgumentAvailabilityOutput,
    )
    from .schema.state import ArgumentRecord, parse_serialized_payload
    from .threads import complete_thread, dialogue_history
except ImportError:  # pragma: no cover - supports LangGraph file-path loading.
    from arguments import (
        argument_body_json,
        generate_attack,
        generate_undercut,
    )
    from defeats import run_defeat_subgraph, run_strict_defeat_subgraph
    from llm import (
        call_llm_messages,
        invoke_agent_structured,
        invoke_agent_structured_messages,
    )
    from prompt_builders import (
        build_generalization_prompt,
        build_integration_prompt,
        build_main_argument_messages,
        compose_system,
    )
    from prompts import PromptTemplates
    from schema.llm_outputs import (
        GeneralizationOutput,
        IntegrationOutput,
        MainArgumentAvailabilityOutput,
    )
    from schema.state import ArgumentRecord, parse_serialized_payload
    from threads import complete_thread, dialogue_history


async def can_generate_main(state: Any) -> dict[str, Any]:
    """Proponent が新しい主張 (A) を生成できるか判定し、可能なら生成して返す。"""
    agent = state.current_proponent
    messages = build_main_argument_messages(state, agent)
    output = await invoke_agent_structured_messages(
        messages,
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

    argument = ArgumentRecord(
        type="main",
        argument=argument_body_json(output.Argument),
        support=[],
        agent=agent,
        round=state.debate_round,
    )
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


async def o_defeat_a(state: Any) -> dict[str, Any]:
    """Opponent が Proponent の主張 A を攻撃する論証 (B) を生成する。"""
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


async def validate_b_defeats_a(state: Any) -> dict[str, Any]:
    """B が A を defeat するか検証する。防御側の undercut があれば defeat を阻止する。"""
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


async def p_counter_b(state: Any) -> dict[str, Any]:
    """Proponent が Opponent の攻撃 B に対してカウンター論証 (C) を生成する。"""
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


async def validate_c_defeats_b(state: Any) -> dict[str, Any]:
    """C が B を defeat するか検証する。defeat できなければ Proponent の主張は overruled。"""
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


async def validate_b_defeats_c(state: Any) -> dict[str, Any]:
    """C が B を strictly defeat するか検証する。B が C を逆 defeat できなければ Proponent の主張は justified。"""
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


async def extract_warrants(state: Any) -> dict[str, Any]:
    """AG1 と AG2 の主張それぞれの最終ルール (warrant) を抽出する。"""
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


async def generalize(state: Any) -> dict[str, Any]:
    """両エージェントの warrant を汎化し、再利用可能な基準を導出する。"""
    if state.warrant_result is None:
        return {"error": "Cannot generalize without warrants."}
    task_system, user_prompt = build_generalization_prompt(
        state.warrant_result,
        json.dumps(state.dialogue_history, ensure_ascii=False, indent=2),
    )
    output = await invoke_agent_structured(
        compose_system(state.agent1_stance, task_system),
        user_prompt,
        GeneralizationOutput,
    )
    response = json.dumps(output.model_dump(exclude_none=True), ensure_ascii=False, indent=2)
    return {"generalization_result": response}


async def integrate(state: Any) -> dict[str, Any]:
    """汎化された基準を一つの統合ルールにまとめ、次ラウンドで再利用できる形にする。"""
    if state.warrant_result is None or state.generalization_result is None:
        return {"error": "Cannot integrate without warrants and generalization."}
    task_system, user_prompt = build_integration_prompt(
        state.warrant_result, state.generalization_result
    )
    output = await invoke_agent_structured(
        compose_system(state.agent1_stance, task_system),
        user_prompt,
        IntegrationOutput,
    )
    response = json.dumps(output.model_dump(exclude_none=True), ensure_ascii=False, indent=2)
    rule = extract_integrated_rule(response)
    if rule is None:
        return {"error": "統合結果から新しいルールを抽出できませんでした"}
    return {"integration_result": response, "integrated_rule": rule}


def extract_integrated_rule(integration_result: str) -> str | None:
    data = parse_serialized_payload(integration_result)
    argument = data.get("Argument", {})
    rule = argument.get("rule") if isinstance(argument, dict) else None
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
    """統合ルールを integrated_rules に追加し、次の debate round の初期状態にリセットする。"""
    if not state.integrated_rule:
        return {"error": "No integrated rule to add."}
    rules = [*state.integrated_rules]
    if state.integrated_rule not in rules:
        rules.append(state.integrated_rule)
    new_round = state.debate_round + 1
    return {
        "debate_round": new_round,
        # 次ラウンドが上限に達したら debate せず暫定回答へ（無限ループ防止）。
        "finalize_mode": new_round >= state.max_turns,
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


async def finalize_fallback(state: Any) -> dict[str, Any]:
    """ラウンド上限到達時、integration rule で作った main arg を暫定回答の土台に据える。

    debate を経た justified ではないため、合意なし (consensus_reached=False) を明示する。
    """
    if state.current_argument is None:
        return {"error": "No integrated main argument available for fallback finalization."}
    return {
        "justified_argument": state.current_argument.argument,
        "justification_status": "fallback_no_consensus",
        "consensus_reached": False,
    }


async def generate_final_answer(state: Any) -> dict[str, Any]:
    """対話履歴を踏まえて自然文回答を生成する。

    通常は justified な主張から作る。合意に至らず暫定回答を作る場合
    (consensus_reached is False) は、合意なしであることを明示する専用プロンプトを使う。
    """
    justified = state.justified_argument
    if not justified:
        return {"final_answer": None, "consensus_reached": state.consensus_reached}

    status = state.justification_status or ""
    if status.startswith("ag2"):
        stance = state.agent2_stance
    else:
        stance = state.agent1_stance

    import json as _json
    import os
    from langchain_core.messages import HumanMessage, SystemMessage

    dialogue_history_str = _json.dumps(state.dialogue_history, ensure_ascii=False, indent=2)

    if state.consensus_reached is False:
        integrated_rules_str = "\n".join(f"- {rule}" for rule in state.integrated_rules) or "(none)"
        system_prompt = compose_system(stance, PromptTemplates.FINAL_ANSWER_NO_CONSENSUS_SYSTEM)
        user_prompt = PromptTemplates.FINAL_ANSWER_NO_CONSENSUS_USER.format(
            question=state.question,
            integrated_rules=integrated_rules_str,
            dialogue_history=dialogue_history_str,
            justified_argument=justified,
        ).strip()
    else:
        system_prompt = compose_system(stance, PromptTemplates.FINAL_ANSWER_SYSTEM)
        user_prompt = PromptTemplates.FINAL_ANSWER_USER.format(
            question=state.question,
            dialogue_history=dialogue_history_str,
            justified_argument=justified,
        ).strip()

    answer = await call_llm_messages(
        [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)],
        model=os.getenv("MODEL", "gpt-5-mini"),
    )
    return {"final_answer": answer, "consensus_reached": state.consensus_reached}


async def route_after_thread_node(state: Any) -> dict[str, Any]:
    """スレッド完了後の条件分岐エッジが参照するランディングノード。本体は空。"""
    return {}


async def finish(state: Any) -> dict[str, Any]:
    """議論を正常終了し、対話履歴・正当化結果・統合ルールを最終状態として返す。"""
    return {
        "dialogue_history": dialogue_history(state.history),
        "justified_argument": state.justified_argument,
        "justification_status": state.justification_status,
        "consensus_reached": state.consensus_reached,
        "final_rebuttal": state.final_rebuttal,
        "final_answer": state.final_answer,
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
    """エラー情報を付与した状態で議論を終了する。"""
    result = await finish(state)
    result["error"] = state.error
    return result
