"""Graph node functions for the dialectical workflow.

ノードは「`arguments.generate_*` を呼んで結果を状態 dict に整形する」ことに専念する。
スレッド進行の簿記ヘルパ（dialogue_history / complete_thread 等）も本ファイルに置く。
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from . import arguments
from .arguments import argument_message_content, generate_attack, generate_undercut
from .defeats import run_defeat_subgraph, run_strict_defeat_subgraph
from .prompts import attack_instruction, main_instruction
from .schema.state import ArgumentRecord, parse_serialized_payload

# ============================================================================
# スレッド進行の簿記ヘルパ（旧 threads.py から移設）
# ============================================================================


def dialogue_history(history: list[ArgumentRecord]) -> list[dict[str, Any]]:
    """引数履歴を対話ログ用の dict リストへ変換する."""
    return [argument.to_dialogue_dict() for argument in history]


def _records(state: Any) -> list[ArgumentRecord]:
    """簿記用 ArgumentRecord リストを返す（移行前 history への互換も含む）."""
    records = getattr(state, "argument_records", None)
    if records is not None:
        return list(records)
    return [
        item
        for item in getattr(state, "history", [])
        if isinstance(item, ArgumentRecord)
    ]


def _message_history(state: Any) -> list[BaseMessage]:
    """LLM 用 BaseMessage 履歴を返す."""
    return [
        item for item in getattr(state, "history", []) if isinstance(item, BaseMessage)
    ]


def _append_turn(
    state: Any, instruction: str, argument: ArgumentRecord
) -> list[BaseMessage]:
    """実際に送った HumanMessage と発話 AIMessage を履歴に追加する."""
    return [
        *_message_history(state),
        HumanMessage(content=instruction),
        AIMessage(content=argument_message_content(argument), name=argument.agent),
    ]


def thread_finding(state: Any, status: str) -> str | None:
    """スレッド結果から、次の主張生成へ渡す learned finding 文を生成する."""
    if state.current_argument is None or state.b_argument is None:
        return None
    main_conclusion = (
        "; ".join(state.current_argument.conclusions) or "the previous main argument"
    )
    defeating_conclusion = (
        "; ".join(state.b_argument.conclusions) or "the defeating argument"
    )
    if status == "overruled":
        return (
            f"{state.current_proponent}'s previous main argument ({main_conclusion}) was overruled by "
            f"{state.current_opponent}'s {state.b_argument.attack} ({defeating_conclusion}). "
            "Do not repeat the same main argument unless this defeating reason is resolved."
        )
    if status == "defensible":
        return (
            f"{state.current_proponent}'s previous main argument ({main_conclusion}) remained defensible, "
            f"with an unresolved conflict against {state.current_opponent}'s {state.b_argument.attack} "
            f"({defeating_conclusion}). "
            "Do not repeat the same main argument as if the conflict were resolved."
        )
    return None


def _annotate_main_status(
    history: list[ArgumentRecord], main_id: str | None, status: str
) -> list[ArgumentRecord]:
    """スレッド完了時、対象 main レコードの status を後追いで埋める（不変＝コピーで差し替え）."""
    if main_id is None:
        return history
    return [
        record.model_copy(update={"status": status}) if record.id == main_id else record
        for record in history
    ]


def complete_thread(
    state: Any,
    status: str,
    extra_history: list[ArgumentRecord] | None = None,
) -> dict[str, Any]:
    """スレッド完了時の状態更新 dict（履歴・status・合意フラグ等）を組み立てる."""
    key = "ag1" if state.current_proponent == "AG1" else "ag2"
    main_id = state.current_argument.id if state.current_argument else None
    records = _annotate_main_status(
        [*_records(state), *(extra_history or [])], main_id, status
    )
    update: dict[str, Any] = {
        "current_thread_status": status,
        "argument_records": records,
        "dialogue_history": dialogue_history(records),
        f"{key}_thread_status": status,
    }

    finding = thread_finding(state, status)
    if finding is not None and finding not in state.learned_findings:
        update["learned_findings"] = [*state.learned_findings, finding]
        update[f"{key}_revision_context"] = finding

    if status == "justified":
        update["justified_argument"] = (
            state.current_argument.argument if state.current_argument else None
        )
        update["justification_status"] = f"{key}_main_justified"
        update["consensus_reached"] = True
    elif status == "overruled":
        update["justification_status"] = f"{key}_main_overruled"

    return update


async def can_generate_main(state: Any) -> dict[str, Any]:
    """Proponent が新しい主張 (A) を生成できるか判定し、可能なら生成して返す."""
    agent = state.current_proponent
    result = await arguments.generate_main(state, agent)
    update: dict[str, Any] = {
        "main_argument_available": result.available,
        "main_argument_unavailable_reason": None if result.available else result.reason,
    }
    if not result.available:
        update["justification_status"] = "no_new_main_argument"
        return update

    if result.argument is None:
        return {
            "error": "Main argument availability was YES but no Argument was generated.",
            "main_argument_available": False,
            "main_argument_unavailable_reason": result.reason,
        }

    argument = result.argument
    instruction = main_instruction(state)
    history = _append_turn(state, instruction, argument)
    records = [*_records(state), argument]
    update.update(
        {
            "active_agent": "AG2" if agent == "AG1" else "AG1",
            "current_argument": argument,
            "current_thread_status": None,
            "main_attempt_count": state.main_attempt_count + 1,
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
            "argument_records": records,
            "dialogue_history": dialogue_history(records),
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


async def advance_to_ag2(state: Any) -> dict[str, Any]:
    """AG1 がこれ以上 main argument を生成できなくなったとき、AG2 の手番に切り替える."""
    return {
        "current_proponent": "AG2",
        "current_opponent": "AG1",
        "active_agent": "AG2",
        "current_argument": None,
        "current_thread_status": None,
        "main_attempt_count": 0,
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
        "debate_stage": "ag2_main_thread",
    }


async def o_defeat_a(state: Any) -> dict[str, Any]:
    """Opponent が Proponent の主張 A を攻撃する論証 (B) を生成する."""
    if state.current_argument is None:
        return {"error": "No current main argument to attack."}
    argument = await generate_attack(
        state,
        state.current_opponent,
        state.current_argument,
        purpose="defeat",
    )
    if argument is None:
        return complete_thread(state, "justified")
    instruction = attack_instruction("defeat", state.current_argument, state=state)
    history = _append_turn(state, instruction, argument)
    records = [*_records(state), argument]
    return {
        "active_agent": state.current_proponent,
        "b_argument": argument,
        "b_argument_id": argument.id,
        "last_generated_argument": argument,
        "last_can_defeat": None,
        "history": history,
        "argument_records": records,
        "dialogue_history": dialogue_history(records),
    }


async def validate_b_defeats_a(state: Any) -> dict[str, Any]:
    """B が A を defeat するか検証する。防御側の undercut があれば defeat を阻止する."""
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
    """Proponent が Opponent の攻撃 B に対してカウンター論証 (C) を生成する."""
    if state.b_argument is None:
        return {"error": "No B argument to counter."}
    argument = await generate_attack(
        state,
        state.current_proponent,
        state.b_argument,
        purpose="counter",
    )
    if argument is None:
        return complete_thread(state, "overruled")
    instruction = attack_instruction(
        "counter", state.b_argument, state=state, main_argument=state.current_argument
    )
    history = _append_turn(state, instruction, argument)
    records = [*_records(state), argument]
    return {
        "active_agent": state.current_opponent,
        "c_argument": argument,
        "c_argument_id": argument.id,
        "last_generated_argument": argument,
        "history": history,
        "argument_records": records,
        "dialogue_history": dialogue_history(records),
    }


async def validate_c_defeats_b(state: Any) -> dict[str, Any]:
    """C が B を defeat するか検証する。defeat できなければ Proponent の主張は overruled."""
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
    """C が B を strictly defeat するか検証する。B が C を逆 defeat できなければ Proponent の主張は justified."""
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
    """AG1 と AG2 の主張それぞれの最終ルール (warrant) を抽出する.

    no_schema では Argument に rules/Conc/Ass の構造がないため、main argument の
    自由記述テキストそのものを warrant として渡す。
    """
    if state.ag1_main_argument is None or state.ag2_main_argument is None:
        return {"error": "AG1またはAG2のmain argumentが見つかりません"}
    if state.output_mode == "no_schema":
        warrant_json = {
            "Argument1": {"agent": "AG1", "warrant": state.ag1_main_argument.argument},
            "Argument2": {"agent": "AG2", "warrant": state.ag2_main_argument.argument},
        }
        return {
            "warrant_result": json.dumps(warrant_json, ensure_ascii=False, indent=2)
        }
    try:
        ag1_last_rule = state.ag1_main_argument.body.get("rules", [])[-1]
        ag2_last_rule = state.ag2_main_argument.body.get("rules", [])[-1]
        warrant_json = {
            "Argument1": {
                "agent": "AG1",
                "warrant": {
                    "antecedent": {
                        "strong": ag1_last_rule["antecedent"].get("strong", []),
                        "weak_negation": ag1_last_rule["antecedent"].get(
                            "weak_negation", []
                        ),
                    },
                    "consequent": ag1_last_rule["consequent"],
                }
            },
            "Argument2": {
                "agent": "AG2",
                "warrant": {
                    "antecedent": {
                        "strong": ag2_last_rule["antecedent"].get("strong", []),
                        "weak_negation": ag2_last_rule["antecedent"].get(
                            "weak_negation", []
                        ),
                    },
                    "consequent": ag2_last_rule["consequent"],
                }
            },
        }
        return {
            "warrant_result": json.dumps(warrant_json, ensure_ascii=False, indent=2)
        }
    except Exception as exc:
        return {"error": f"Warrant抽出中にエラーが発生しました: {exc}"}


async def generalize(state: Any) -> dict[str, Any]:
    """両エージェントの warrant を汎化し、再利用可能な基準を導出する."""
    if state.warrant_result is None:
        return {"error": "Cannot generalize without warrants."}
    output = await arguments.generate_generalization(state)
    response = json.dumps(
        output.model_dump(exclude_none=True), ensure_ascii=False, indent=2
    )
    return {"generalization_result": response}


async def integrate(state: Any) -> dict[str, Any]:
    """汎化された基準を一つの統合ルールにまとめ、次ラウンドで再利用できる形にする."""
    if state.warrant_result is None or state.generalization_result is None:
        return {"error": "Cannot integrate without warrants and generalization."}
    output = await arguments.generate_integration(state)
    response = json.dumps(
        output.model_dump(exclude_none=True), ensure_ascii=False, indent=2
    )
    rule = extract_integrated_rule(response)
    if rule is None:
        return {"error": "統合結果から新しいルールを抽出できませんでした"}
    return {"integration_result": response, "integrated_rule": rule}


def extract_integrated_rule(integration_result: str) -> str | None:
    """統合結果ペイロードから統合ルール文字列を取り出す（プレースホルダは除外）."""
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
    """統合ルールを integrated_rules に追加し、次の debate round の初期状態にリセットする."""
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
        "main_attempt_count": 0,
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
    """ラウンド上限到達時、integration rule で作った main arg を暫定回答の土台に据える.

    debate を経た justified ではないため、合意なし (consensus_reached=False) を明示する。
    """
    if state.current_argument is None:
        return {
            "error": "No integrated main argument available for fallback finalization."
        }
    return {
        "justified_argument": state.current_argument.argument,
        "justification_status": "fallback_no_consensus",
        "consensus_reached": False,
    }


async def generate_final_answer(state: Any) -> dict[str, Any]:
    """対話履歴を踏まえて自然文回答を生成する.

    通常は justified な主張から作る。合意に至らず暫定回答を作る場合
    (consensus_reached is False) は、合意なしであることを明示する専用プロンプトを使う。
    """
    if not state.justified_argument:
        return {"final_answer": None, "consensus_reached": state.consensus_reached}
    answer = await arguments.generate_final_answer(state)
    return {"final_answer": answer, "consensus_reached": state.consensus_reached}


async def route_after_thread_node(state: Any) -> dict[str, Any]:
    """スレッド完了後の条件分岐エッジが参照するランディングノード。本体は空."""
    return {}


async def finish(state: Any) -> dict[str, Any]:
    """議論を正常終了し、対話履歴・正当化結果・統合ルールを最終状態として返す."""
    return {
        "dialogue_history": dialogue_history(_records(state)),
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
    """エラー情報を付与した状態で議論を終了する."""
    result = await finish(state)
    result["error"] = state.error
    return result
