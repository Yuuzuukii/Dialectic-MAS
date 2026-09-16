"""Graph node functions for the dialectical workflow.

ノードは「`arguments.generate_*` を呼んで結果を状態 dict に整形する」ことに専念する。
スレッド進行の簿記ヘルパ（dialogue_history / resolve_tree_status 等）も本ファイルに置く。

dialogue tree（Prakken & Sartor, Definition 4.5/4.6）の探索は、明示的なスタック
（`State.node_stack`）を使った DFS として実装する。LangGraph には再帰呼び出しが
無いため、「Pがある論証を防御している」という1フレームを `DialogueNode` として
`State.dialogue_nodes` に積み、`opponent_move`/`proponent_move` の2種類のノードを
ループさせることで木を掘り下げる。詳細は docs/argumentation_model_rebuild_plan.md を参照。
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from . import arguments
from .argumentation_model import evaluate_attack
from .arguments import (
    argument_message_content,
    ask_attack_extends,
    generate_attack,
    generate_undercut,
)
from .prompts import attack_instruction, main_instruction
from .schema.state import ArgumentRecord, DialogueNode, parse_serialized_payload

# ============================================================================
# 簿記ヘルパ
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


def _per_proponent_dialogue_turn_budget(state: Any) -> int | None:
    """`max_dialogue_turns` を現在の proponent（AG1/AG2）用に按分した予算を返す.

    schema は dialogue tree の探索構造上、片方の main argument を巡る攻防が
    長引くと、もう片方が今ラウンド一度も発言できないまま予算が尽くことがある
    （MAD/Free Debate は厳密な交互発言なので共有予算のままでも自然に均等に割れるが、
    schema は木の深掘り次第で偏るため、明示的に折半する）。奇数の端数は先手（AG1）に
    寄せる。ラウンドをまたいでも累積する絶対予算であり、ラウンドごとにはリセットしない。
    """
    limit = getattr(state, "max_dialogue_turns", None)
    if limit is None:
        return None
    limit = int(limit)
    half, remainder = divmod(limit, 2)
    return half + remainder if state.current_proponent == "AG1" else half


def _dialogue_turn_budget_exceeded(state: Any) -> bool:
    """現在の proponent 用の絶対ターン数上限に既に達しているか（未設定なら常に False）.

    `max_dialogue_turns` の対象は対話フェーズの発話数（main/defeat/counter/undercut
    blocker）だけ。統合（integrate）や最終回答生成はここでは数えない — 統合ステップの
    回数は手法ごとに構造的に異なり（schemaは持つがMAD/Free Debateは持たない）、これを
    共通予算に含めると手法間の対話量そのものの比較が歪むため。

    カウント対象は「誰が発言したか」（`ArgumentRecord.agent`）ではなく「どちらの
    main argument を巡る攻防だったか」（`ArgumentRecord.proponent`）。Opponent が
    攻撃した発言も、Proponent の主張を守る攻防の一部として Proponent 側の予算を消費する。
    """
    limit = _per_proponent_dialogue_turn_budget(state)
    if limit is None:
        return False
    proponent = getattr(state, "current_proponent", "AG1")
    used = sum(1 for record in _records(state) if record.proponent == proponent)
    return used >= limit


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


# ============================================================================
# dialogue tree（DialogueNode）の簿記ヘルパ
# ============================================================================


def _find_node(nodes: list[DialogueNode], node_id: str) -> DialogueNode:
    for node in nodes:
        if node.id == node_id:
            return node
    raise KeyError(f"dialogue node not found: {node_id}")


def _replace_node(
    nodes: list[DialogueNode], node_id: str, **updates: Any
) -> list[DialogueNode]:
    """dialogue_nodes リスト中の1ノードだけを更新したコピーへ差し替える（不変更新）."""
    return [
        node.model_copy(update=updates) if node.id == node_id else node
        for node in nodes
    ]


def _find_argument(state: Any, argument_id: str) -> ArgumentRecord:
    for record in _records(state):
        if record.id == argument_id:
            return record
    raise KeyError(f"argument record not found: {argument_id}")


def _top_frame(state: Any) -> DialogueNode:
    return _find_node(state.dialogue_nodes, state.node_stack[-1])


def thread_finding(state: Any, status: str) -> str | None:
    """スレッド結果から、次の主張生成へ渡す learned finding 文を生成する.

    木がどれだけ深く探索されても、「結局この main argument (A) を最終的に
    立ち行かなくした攻撃は何か」は根フレーム（root）の `current_attacker_id` に
    残る（repel できた B は都度クリアされ、最後まで立ちはだかった B だけが残る）。
    """
    if status not in {"overruled", "defensible"}:
        return None
    if state.current_argument is None or state.root_node_id is None:
        return None
    root = _find_node(state.dialogue_nodes, state.root_node_id)
    if root.current_attacker_id is None:
        return None
    attacker = _find_argument(state, root.current_attacker_id)
    main_conclusion = (
        "; ".join(state.current_argument.conclusions) or "the previous main argument"
    )
    defeating_conclusion = "; ".join(attacker.conclusions) or "the defeating argument"
    if status == "overruled":
        return (
            f"{state.current_proponent}'s previous main argument ({main_conclusion}) was overruled by "
            f"{state.current_opponent}'s {attacker.attack} ({defeating_conclusion}). "
            "Do not repeat the same main argument unless this defeating reason is resolved."
        )
    return (
        f"{state.current_proponent}'s previous main argument ({main_conclusion}) remained defensible, "
        f"with an unresolved conflict against {state.current_opponent}'s {attacker.attack} "
        f"({defeating_conclusion}). "
        "Do not repeat the same main argument as if the conflict were resolved."
    )


def _annotate_main_status(
    history: list[ArgumentRecord],
    main_id: str | None,
    status: str,
    closed_by_budget: bool = False,
) -> list[ArgumentRecord]:
    """スレッド完了時、対象 main レコードの status/closed_by_budget を後追いで埋める（不変＝コピーで差し替え）."""
    if main_id is None:
        return history
    update = {"status": status, "closed_by_budget": closed_by_budget}
    return [
        record.model_copy(update=update) if record.id == main_id else record
        for record in history
    ]


# ============================================================================
# main argument の生成
# ============================================================================

_TREE_RESET_FIELDS: dict[str, Any] = {
    "dialogue_nodes": [],
    "node_stack": [],
    "root_node_id": None,
    "tree_root_status": None,
    "tree_root_closed_by_budget": False,
    "pending_attacker_argument": None,
    "pending_counter_argument": None,
    "last_attack_defeated": None,
    "last_counter_strictly_defeated": None,
    "last_propagation_action": None,
}


async def can_generate_main(state: Any) -> dict[str, Any]:
    """Proponent が新しい主張 (A) を生成できるか判定し、可能なら生成して返す."""
    if _dialogue_turn_budget_exceeded(state):
        return {
            "main_argument_available": False,
            "main_argument_unavailable_reason": (
                "Dialogue turn budget (max_dialogue_turns) reached."
            ),
            "justification_status": "no_new_main_argument",
        }
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

    argument = result.argument.model_copy(update={"proponent": agent})
    instruction = main_instruction(state)
    history = _append_turn(state, instruction, argument)
    records = [*_records(state), argument]
    update.update(
        {
            "active_agent": "AG2" if agent == "AG1" else "AG1",
            "current_argument": argument,
            "history": history,
            "argument_records": records,
            "dialogue_history": dialogue_history(records),
            **_TREE_RESET_FIELDS,
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
        "debate_stage": "ag2_main_thread",
        **_TREE_RESET_FIELDS,
    }


# ============================================================================
# dialogue tree の探索
# ============================================================================


async def init_dialogue_tree(state: Any) -> dict[str, Any]:
    """Dialogue tree の探索を main argument（A）を根として初期化する（深さ0）."""
    if state.current_argument is None:
        return {"error": "No current main argument to build a dialogue tree from."}
    root = DialogueNode(argument_id=state.current_argument.id, depth=0)
    return {
        "dialogue_nodes": [*state.dialogue_nodes, root],
        "node_stack": [*state.node_stack, root.id],
        "root_node_id": root.id,
    }


async def opponent_move(state: Any) -> dict[str, Any]:
    """現フレームで防御中の argument に対し、Opponent が新しい攻撃 (B) を試みる.

    このフレームで O が試せる攻撃の回数に個別の上限は設けない。リソース制約は
    `max_dialogue_turns`（対話全体の絶対予算）だけで課す。これが尽きた場合は
    「この論証が守り切れたか」とは無関係な、実験全体のリソース都合の打ち切りなので、
    won_by_p（→justified）にするのは正当化の水準として強すぎる。`max_tree_depth`
    到達と同じ「undetermined」（→defensible）として閉じる。
    """
    frame = _top_frame(state)
    target = _find_argument(state, frame.argument_id)

    if frame.depth >= state.max_tree_depth:
        nodes_ = _replace_node(state.dialogue_nodes, frame.id, outcome="undetermined")
        return {"dialogue_nodes": nodes_, "pending_attacker_argument": None}
    if _dialogue_turn_budget_exceeded(state):
        nodes_ = _replace_node(state.dialogue_nodes, frame.id, outcome="undetermined")
        return {"dialogue_nodes": nodes_, "pending_attacker_argument": None}

    argument = await generate_attack(
        state,
        state.current_opponent,
        target,
        purpose="defeat",
    )
    if argument is None:
        # Opponent がこの argument への新しい攻撃を1つも思いつけなかった
        # （真の手詰まり）。dialogue tree の "O が手を出せない" 終端条件。
        nodes_ = _replace_node(state.dialogue_nodes, frame.id, outcome="won_by_p")
        return {"dialogue_nodes": nodes_, "pending_attacker_argument": None}

    argument = argument.model_copy(update={"proponent": state.current_proponent})
    instruction = attack_instruction("defeat", target, state=state)
    history = _append_turn(state, instruction, argument)
    records = [*_records(state), argument]
    return {
        "active_agent": state.current_proponent,
        "pending_attacker_argument": argument,
        "last_generated_argument": argument,
        "history": history,
        "argument_records": records,
        "dialogue_history": dialogue_history(records),
    }


async def validate_opponent_move(state: Any) -> dict[str, Any]:
    """B が現フレームの argument を defeat するか検証する。防御側の undercut があれば阻止."""
    frame = _top_frame(state)
    target = _find_argument(state, frame.argument_id)
    attacker = state.pending_attacker_argument
    if attacker is None:
        return {"error": "No pending attacker argument to validate."}

    result = await evaluate_attack(
        state,
        attacker,
        target,
        state.current_proponent,
        relation_context=f"{attacker.id} defeats {target.id}",
        blocker_generator=None
        if _dialogue_turn_budget_exceeded(state)
        else generate_undercut,
    )
    relations = [*state.defeat_relations, *result.relations]
    if not result.defeats:
        # B は target を defeat できなかった。このフレームで別の攻撃 B' を試させる。
        # 阻止に使った undercut（blocker）は、続くか終わるかに関わらず履歴に残す。
        nodes_ = _replace_node(
            state.dialogue_nodes, frame.id, attack_attempts=frame.attack_attempts + 1
        )
        update: dict[str, Any] = {
            "dialogue_nodes": nodes_,
            "defeat_relations": relations,
            "pending_attacker_argument": None,
            "last_attack_defeated": False,
        }
        if result.blocker is not None:
            blocker = result.blocker.model_copy(
                update={"proponent": state.current_proponent}
            )
            records = [*_records(state), blocker]
            update["last_generated_argument"] = blocker
            update["argument_records"] = records
            update["dialogue_history"] = dialogue_history(records)
        return update

    nodes_ = _replace_node(
        state.dialogue_nodes,
        frame.id,
        current_attacker_id=attacker.id,
        counter_attempts=0,
    )
    return {
        "dialogue_nodes": nodes_,
        "defeat_relations": relations,
        "pending_attacker_argument": None,
        "last_attack_defeated": True,
    }


async def proponent_move(state: Any) -> dict[str, Any]:
    """現フレームの攻撃者 (B) に対し、Proponent が反論 (C) を試みる.

    `max_counter_attempts`（同じ B に対して P が試せる反論の回数）も
    Prakken & Sartor の理論には存在しない実装上の拡張である。理論上は
    「B を strictly defeat する C が存在するか」を無限に探索してよいが、
    LLM が都度生成する以上、有限回で打ち切る安全装置が要る。予算切れは
    「見つからなかった」という弱い意味の lost_by_p（closed_by_budget=True）とする。

    `max_dialogue_turns`（対話全体の絶対予算）が尽きた場合はこのフレーム固有の
    話ではないので、opponent_move と同様 undetermined（→defensible）として扱う。
    """
    frame = _top_frame(state)
    if frame.current_attacker_id is None:
        return {"error": "No current attacker to counter."}
    attacker = _find_argument(state, frame.current_attacker_id)
    main_argument = _find_argument(state, frame.argument_id)

    if frame.counter_attempts >= state.max_counter_attempts:
        nodes_ = _replace_node(
            state.dialogue_nodes, frame.id, outcome="lost_by_p", closed_by_budget=True
        )
        return {"dialogue_nodes": nodes_, "pending_counter_argument": None}
    if _dialogue_turn_budget_exceeded(state):
        nodes_ = _replace_node(state.dialogue_nodes, frame.id, outcome="undetermined")
        return {"dialogue_nodes": nodes_, "pending_counter_argument": None}

    argument = await generate_attack(
        state, state.current_proponent, attacker, purpose="counter"
    )
    if argument is None:
        # Proponent がこの B に反論する論証を1つも思いつけなかった（真の手詰まり）。
        nodes_ = _replace_node(state.dialogue_nodes, frame.id, outcome="lost_by_p")
        return {"dialogue_nodes": nodes_, "pending_counter_argument": None}

    argument = argument.model_copy(update={"proponent": state.current_proponent})
    instruction = attack_instruction(
        "counter", attacker, state=state, main_argument=main_argument
    )
    history = _append_turn(state, instruction, argument)
    records = [*_records(state), argument]
    return {
        "active_agent": state.current_opponent,
        "pending_counter_argument": argument,
        "last_generated_argument": argument,
        "history": history,
        "argument_records": records,
        "dialogue_history": dialogue_history(records),
    }


async def validate_proponent_move(state: Any) -> dict[str, Any]:
    """C が B を strictly defeat するか検証する（C defeats B かつ not B defeats C）.

    strictly defeat していれば、C を argument_id とする子フレームを push して
    探索を1段深くする（Definition 4.6: Pの手番の子は、その論証に対する
    Oの defeater 全て。つまり C 自身も次の攻撃対象になる）。
    """
    frame = _top_frame(state)
    if frame.current_attacker_id is None:
        return {"error": "No current attacker to validate against."}
    b_argument = _find_argument(state, frame.current_attacker_id)
    c_argument = state.pending_counter_argument
    if c_argument is None:
        return {"error": "No pending counter argument to validate."}

    result = await evaluate_attack(
        state,
        c_argument,
        b_argument,
        state.current_opponent,
        relation_context=f"{c_argument.id} defeats {b_argument.id}",
        blocker_generator=None
        if _dialogue_turn_budget_exceeded(state)
        else generate_undercut,
    )
    relations = [*state.defeat_relations, *result.relations]
    if not result.defeats:
        nodes_ = _replace_node(
            state.dialogue_nodes, frame.id, counter_attempts=frame.counter_attempts + 1
        )
        return {
            "dialogue_nodes": nodes_,
            "defeat_relations": relations,
            "pending_counter_argument": None,
            "last_counter_strictly_defeated": False,
        }

    # B はもともと別の対象（A、またはこのフレームの argument）を狙って宣言された
    # 攻撃なので、その .attack/target_statement を C にそのまま使い回さない
    # （Prakken & Sartor の attack/defeat は論証単体の性質ではなく「特定の2論証の組」
    # に対して定義される関係。B が A に対して undercut だったからといって、C に
    # 対しても undercut として無条件に勝てるとは限らない）。ask_attack_extends が
    # B-C 間の攻撃関係を C の中身を見た上で改めて宣言し、それだけを判定に使う。
    reverse_match = await ask_attack_extends(
        state, state.current_opponent, b_argument, c_argument
    )
    if reverse_match is not None:
        b_for_reverse = b_argument.model_copy(
            update={
                "attack": reverse_match.method,
                "target_field": reverse_match.field,
                "target_statement": reverse_match.statement,
            }
        )
        reverse = await evaluate_attack(
            state,
            b_for_reverse,
            c_argument,
            state.current_proponent,
            relation_context=f"{b_argument.id} defeats {c_argument.id}",
            blocker_generator=None
            if _dialogue_turn_budget_exceeded(state)
            else generate_undercut,
            # b_for_reverse は B-C 間専用に作った一時コピー。判定結果として B の
            # 本来（A向け）の attack 宣言を上書きしてはならない。
            persist_metadata=False,
        )
        relations = [*relations, *reverse.relations]
        if reverse.defeats:
            # B が C にも反撃できる＝相互 defeat＝C は B を strictly defeat していない。
            nodes_ = _replace_node(
                state.dialogue_nodes,
                frame.id,
                counter_attempts=frame.counter_attempts + 1,
            )
            return {
                "dialogue_nodes": nodes_,
                "defeat_relations": relations,
                "pending_counter_argument": None,
                "last_counter_strictly_defeated": False,
            }

    # C が B を strictly defeat した。C を新しいフレームとして push し、
    # 探索を1段深くする（C 自身が次の攻撃対象になる）。
    child = DialogueNode(
        parent_id=frame.id, argument_id=c_argument.id, depth=frame.depth + 1
    )
    nodes_ = [*state.dialogue_nodes, child]
    return {
        "dialogue_nodes": nodes_,
        "node_stack": [*state.node_stack, child.id],
        "defeat_relations": relations,
        "pending_counter_argument": None,
        "last_counter_strictly_defeated": True,
    }


async def pop_and_propagate(state: Any) -> dict[str, Any]:
    """スタック最上位の閉じたフレームを pop し、結果を親フレームへ伝播する（AND/OR 集約）.

    - 子（B への反論 C）が生き残った(won_by_p) ＝ この B は撃退された
      → 親フレームは次の B を探しに `opponent_move` へ戻る。
    - 子が生き残れなかった(lost_by_p/undetermined) ＝ この B は最終的に撃退できなかった
      → 親フレーム全体が負ける（AND 条件: 1つでも撃退できない攻撃があれば親は負け）。
        親を lost_by_p にして、さらに1段上へ伝播する（`pop_and_propagate` を再度呼ぶ）。
    - 親が無い（根が閉じた）→ status を確定し `resolve_tree_status` へ。
    """
    closed_id = state.node_stack[-1]
    closed = _find_node(state.dialogue_nodes, closed_id)
    new_stack = state.node_stack[:-1]

    if not new_stack:
        if closed.outcome == "won_by_p":
            status = "justified"
        elif closed.outcome == "lost_by_p" and not closed.closed_by_budget:
            status = "overruled"
        else:
            status = "defensible"
        return {
            "node_stack": new_stack,
            "tree_root_status": status,
            "tree_root_closed_by_budget": (
                closed.closed_by_budget or closed.outcome == "undetermined"
            ),
            "last_propagation_action": "resolved",
        }

    parent_id = new_stack[-1]
    parent = _find_node(state.dialogue_nodes, parent_id)

    if closed.outcome == "won_by_p":
        nodes_ = _replace_node(
            state.dialogue_nodes,
            parent.id,
            attack_attempts=parent.attack_attempts + 1,
            current_attacker_id=None,
            counter_attempts=0,
        )
        return {
            "dialogue_nodes": nodes_,
            "node_stack": new_stack,
            "last_propagation_action": "retry_attack",
        }

    nodes_ = _replace_node(
        state.dialogue_nodes,
        parent.id,
        outcome="lost_by_p",
        closed_by_budget=closed.closed_by_budget or closed.outcome == "undetermined",
    )
    return {
        "dialogue_nodes": nodes_,
        "node_stack": new_stack,
        "last_propagation_action": "cascade",
    }


async def resolve_tree_status(state: Any) -> dict[str, Any]:
    """根フレームの outcome から justified/overruled/defensible を確定し、簿記を行う."""
    status = state.tree_root_status
    key = "ag1" if state.current_proponent == "AG1" else "ag2"
    main_id = state.current_argument.id if state.current_argument else None
    records = _annotate_main_status(
        _records(state), main_id, status, state.tree_root_closed_by_budget
    )
    update: dict[str, Any] = {
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


# ============================================================================
# 統合フェーズ
# ============================================================================


async def extract_warrants(state: Any) -> dict[str, Any]:
    """AG1 と AG2 の主張それぞれの最終ルール (warrant) を抽出する.

    no_schema では Argument に rules/Conc/Ass の構造がないため、main argument の
    自由記述テキストそのものを warrant として渡す。

    どちらか一方が新しい main argument を生成できなかった場合（次ラウンド用の
    ルールを両者から統合する材料が揃わない場合）は、ここをエラーにはしない。
    次ラウンドは行われない（route_after_extract_warrants が generalize/integrate を
    スキップし、finalize_fallback へ進める）ので、この関数としては何もせず返す。
    """
    if state.ag1_main_argument is None or state.ag2_main_argument is None:
        return {}
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
                },
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
                },
            },
        }
        return {
            "warrant_result": json.dumps(warrant_json, ensure_ascii=False, indent=2)
        }
    except Exception as exc:
        return {"error": f"Warrant抽出中にエラーが発生しました: {exc}"}


async def integrate(state: Any) -> dict[str, Any]:
    """両エージェントの warrant を汎化した上で一つの統合ルールにまとめ、次ラウンドで再利用できる形にする."""
    if state.warrant_result is None:
        return {"error": "Cannot integrate without warrants."}
    output = await arguments.generate_integration(state)
    response = json.dumps(
        output.model_dump(exclude_none=True), ensure_ascii=False, indent=2
    )
    rule = extract_integrated_rule(response)
    if rule is None:
        return {"error": "統合結果から新しいルールを抽出できませんでした"}
    return {"integration_result": response, "integrated_rule": rule}


def extract_integrated_rule(integration_result: str) -> str | None:
    """統合結果ペイロードから統合ルール文字列を取り出す."""
    data = parse_serialized_payload(integration_result)
    argument = data.get("Argument", {})
    rule = argument.get("rule") if isinstance(argument, dict) else None
    if isinstance(rule, str) and rule.strip():
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
        "integrated_rules": rules,
        "current_proponent": "AG1",
        "current_opponent": "AG2",
        "active_agent": "AG1",
        "debate_stage": "ag1_main_thread",
        "ag1_main_argument": None,
        "ag2_main_argument": None,
        "ag1_thread_status": None,
        "ag2_thread_status": None,
        "current_argument": None,
        "warrant_result": None,
        "integration_result": None,
        "integrated_rule": None,
        **_TREE_RESET_FIELDS,
    }


async def finalize_fallback(state: Any) -> dict[str, Any]:
    """ラウンド上限到達時、integration rule で作った main arg を暫定回答の土台に据える.

    debate を経た justified ではないため、合意なし (consensus_reached=False) を明示する。
    finalize ラウンドで新しい main argument が一つも生成されなかった場合（双方が
    "main_argument_available=False" と判定した場合）は、current_argument が無いため、
    代わりに直前までに積まれた integrated_rules の最後のルールを土台にする。
    それも無ければ（統合ラウンドが一度も完了していない1ラウンド目などでは）、
    片方のエージェントだけが今回 main argument を生成できていた可能性があるので、
    ag1_main_argument / ag2_main_argument のうち存在する方を土台にする
    （もう片方は新しい主張を生成できなかった、という結果自体を反映する）。
    """
    if state.current_argument is not None:
        justified_argument = state.current_argument.argument
    elif state.integrated_rules:
        justified_argument = state.integrated_rules[-1]
    elif state.ag1_main_argument is not None:
        justified_argument = state.ag1_main_argument.argument
    elif state.ag2_main_argument is not None:
        justified_argument = state.ag2_main_argument.argument
    else:
        return {
            "error": "No integrated main argument available for fallback finalization."
        }
    return {
        "justified_argument": justified_argument,
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
