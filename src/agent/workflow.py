"""議論ワークフローの状態定義と LangGraph グラフの構築."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from langchain_core.messages import BaseMessage
from langgraph.graph import END, START, StateGraph

from .edges import (
    _int_env,
    _optional_int_env,
    route_after_can_generate_main,
    route_after_extract_warrants,
    route_after_init_dialogue_tree,
    route_after_opponent_move,
    route_after_pop_and_propagate,
    route_after_proponent_move,
    route_after_resolve_tree_status,
    route_after_synthesis_step,
    route_after_validate_opponent_move,
    route_after_validate_proponent_move,
    route_round_entry,
)
from .nodes import (
    add_integrated_rule,
    advance_to_ag2,
    can_generate_main,
    extract_warrants,
    finalize_fallback,
    finish,
    finish_with_error,
    generate_final_answer,
    init_dialogue_tree,
    integrate,
    opponent_move,
    pop_and_propagate,
    proponent_move,
    resolve_tree_status,
    validate_opponent_move,
    validate_proponent_move,
)
from .schema.state import ArgumentRecord, DefeatRelation, DialogueNode
from .schema.types import AgentName, DebateStage


@dataclass
class State:
    """議論グラフ全体で共有される可変状態."""

    question: str
    agent1_stance: str
    agent2_stance: str
    # 議論ラウンド（debate_round）の上限。環境変数 MAX_TURNS で上書きできる。
    max_turns: int = _int_env("MAX_TURNS", 5)
    # dialogue tree の1フレームで、Opponent が攻撃 (B) を再生成できる回数の上限（安全装置）。
    # 環境変数 MAX_ATTACK_ATTEMPTS で上書きできる。
    max_attack_attempts: int = _int_env("MAX_ATTACK_ATTEMPTS", 5)
    # dialogue tree の1フレームで、Proponent が同じ B に対して反論 (C) を
    # 再生成できる回数の上限（安全装置）。Prakken & Sartor の理論には存在しない
    # 実装上の拡張で、「strictly defeat する C が存在するか」を有限回で打ち切る。
    max_counter_attempts: int = _int_env("MAX_COUNTER_ATTEMPTS", 3)
    # dialogue tree の最大深さ（根を 0 とする）。原論文は有限のルール集合を前提に
    # 探索が必ず停止することを保証するが（Section 8）、LLM は都度論証を生成するため
    # 停止保証がない。深さの安全装置として導入する。
    max_tree_depth: int = _int_env("MAX_TREE_DEPTH", 6)
    # 全手法（schema/no_schema/mad/free_debate）で共通の、対話ターン数そのものの絶対上限。
    # None（既定）なら無効で、上記の max_turns/max_attack_attempts だけで従来通り動く。
    # 設定すると、mainやattackを新たに生成する直前でこの上限を優先チェックし、達していれば
    # 通常の「もう新しい手番がない」経路（no_new_main_argument/defensible）に合流させる。
    # mad/free_debateの`max_turns`（ラウンド数）とは異なり、片方の発言だけでも1ターンと
    # 数える絶対値。手法間でターン数（＝主張・反論の機会の総数）を揃えて比較したい場合に使う。
    max_dialogue_turns: int | None = _optional_int_env("MAX_DIALOGUE_TURNS")
    additional_context: dict[str, Any] = field(default_factory=dict)
    # "schema": Argument 本体（rules/Conc/Ass）も with_structured_output のスキーマで強制する。
    # "no_schema": 同一プロンプト・同一グラフだが、Argument 本体は自由記述の natural language。
    # can_generate/can_defeat/can_undercut の可否判定と Attack（rebut/undercut + target）は
    # 弁証法的な状態遷移の機械的決定のため両条件で構造化出力のまま保持する。
    output_mode: Literal["schema", "no_schema"] = "schema"

    debate_round: int = 1
    learned_findings: list[str] = field(default_factory=list)
    integrated_rules: list[str] = field(default_factory=list)

    # justified な決着（合意）に至ったか。fallback 暫定回答では False。
    consensus_reached: bool | None = None

    active_agent: AgentName = "AG1"
    current_proponent: AgentName = "AG1"
    current_opponent: AgentName = "AG2"
    debate_stage: DebateStage = "ag1_main_thread"
    turn_count: int = 0

    # dialogue tree（Prakken & Sartor, Definition 4.5/4.6）の explicit stack。
    # 各要素は DialogueNode.id。末尾が現在探索中のフレーム。LangGraph に再帰呼び出しは
    # ないため、木構造の探索状態をここに持たせ、opponent_move/proponent_move を
    # ループさせることで DFS を実現する（詳細: docs/argumentation_model_rebuild_plan.md）。
    dialogue_nodes: list[DialogueNode] = field(default_factory=list)
    node_stack: list[str] = field(default_factory=list)
    root_node_id: str | None = None
    # 根フレームが閉じた結果（"justified"/"overruled"/"defensible"）。
    # スタックが空になった時点で確定する。
    tree_root_status: str | None = None
    tree_root_closed_by_budget: bool = False

    # opponent_move/proponent_move が生成した「検証待ち」の論証。
    # validate_opponent_move/validate_proponent_move が読み、検証後に None へ戻す。
    pending_attacker_argument: ArgumentRecord | None = None
    pending_counter_argument: ArgumentRecord | None = None
    # 直前の検証結果（ルーティング専用の一時フラグ）。
    last_attack_defeated: bool | None = None
    last_counter_strictly_defeated: bool | None = None
    last_propagation_action: Literal["retry_attack", "cascade", "resolved"] | None = None

    # LLM に再送する通常の対話履歴。各ターンは HumanMessage(question/instruction)
    # と AIMessage(Argument only, name=agent) のペアとして保存する。
    history: list[BaseMessage] = field(default_factory=list)
    # 検証・target 解決・出力ログ用の構造化された論証簿記。
    argument_records: list[ArgumentRecord] = field(default_factory=list)
    dialogue_history: list[dict[str, Any]] = field(default_factory=list)
    defeat_relations: list[DefeatRelation] = field(default_factory=list)
    ag1_revision_context: str | None = None
    ag2_revision_context: str | None = None

    current_argument: ArgumentRecord | None = None
    ag1_main_argument: ArgumentRecord | None = None
    ag2_main_argument: ArgumentRecord | None = None
    ag1_current_main_id: str | None = None
    ag2_current_main_id: str | None = None
    main_argument_available: bool | None = None
    main_argument_unavailable_reason: str | None = None
    ag1_thread_status: str | None = None
    ag2_thread_status: str | None = None

    # Compatibility fields used by def.py and existing result consumers.
    ag1_rejection_rebuttal: str | None = None
    ag1_pending: bool = False
    ag2_pending: bool = False
    last_can_defeat: bool | None = None
    last_generated_argument: ArgumentRecord | None = None
    last_generated_argument_appended: bool = False
    final_rebuttal: str | None = None

    warrant_result: str | None = None
    integration_result: str | None = None
    integrated_rule: str | None = None

    justified_argument: str | None = None
    justification_status: str | None = None
    final_answer: str | None = None
    error: str | None = None


graph = (
    StateGraph(State)
    .add_node("can_generate_main", can_generate_main)
    .add_node("finalize_fallback", finalize_fallback)
    .add_node("init_dialogue_tree", init_dialogue_tree)
    .add_node("opponent_move", opponent_move)
    .add_node("validate_opponent_move", validate_opponent_move)
    .add_node("proponent_move", proponent_move)
    .add_node("validate_proponent_move", validate_proponent_move)
    .add_node("pop_and_propagate", pop_and_propagate)
    .add_node("resolve_tree_status", resolve_tree_status)
    .add_node("extract_warrants", extract_warrants)
    .add_node("integrate", integrate)
    .add_node("add_integrated_rule", add_integrated_rule)
    .add_node("generate_final_answer", generate_final_answer)
    .add_node("advance_to_ag2", advance_to_ag2)
    .add_node("finish", finish)
    .add_node("finish_with_error", finish_with_error)
    .add_conditional_edges(
        START,
        route_round_entry,
        {
            "can_generate_main": "can_generate_main",
            "finalize_fallback": "finalize_fallback",
            "finish_with_error": "finish_with_error",
        },
    )
    .add_conditional_edges(
        "can_generate_main",
        route_after_can_generate_main,
        {
            "init_dialogue_tree": "init_dialogue_tree",
            "advance_to_ag2": "advance_to_ag2",
            "extract_warrants": "extract_warrants",
            "finish_with_error": "finish_with_error",
        },
    )
    .add_edge("advance_to_ag2", "can_generate_main")
    .add_edge("finalize_fallback", "generate_final_answer")
    .add_conditional_edges(
        "init_dialogue_tree",
        route_after_init_dialogue_tree,
        {
            "opponent_move": "opponent_move",
            "finish_with_error": "finish_with_error",
        },
    )
    .add_conditional_edges(
        "opponent_move",
        route_after_opponent_move,
        {
            "validate_opponent_move": "validate_opponent_move",
            "pop_and_propagate": "pop_and_propagate",
            "finish_with_error": "finish_with_error",
        },
    )
    .add_conditional_edges(
        "validate_opponent_move",
        route_after_validate_opponent_move,
        {
            "proponent_move": "proponent_move",
            "opponent_move": "opponent_move",
            "finish_with_error": "finish_with_error",
        },
    )
    .add_conditional_edges(
        "proponent_move",
        route_after_proponent_move,
        {
            "validate_proponent_move": "validate_proponent_move",
            "pop_and_propagate": "pop_and_propagate",
            "finish_with_error": "finish_with_error",
        },
    )
    .add_conditional_edges(
        "validate_proponent_move",
        route_after_validate_proponent_move,
        {
            "opponent_move": "opponent_move",
            "proponent_move": "proponent_move",
            "finish_with_error": "finish_with_error",
        },
    )
    .add_conditional_edges(
        "pop_and_propagate",
        route_after_pop_and_propagate,
        {
            "resolve_tree_status": "resolve_tree_status",
            "opponent_move": "opponent_move",
            "pop_and_propagate": "pop_and_propagate",
            "finish_with_error": "finish_with_error",
        },
    )
    .add_conditional_edges(
        "resolve_tree_status",
        route_after_resolve_tree_status,
        {
            "advance_to_ag2": "advance_to_ag2",
            "extract_warrants": "extract_warrants",
            "generate_final_answer": "generate_final_answer",
            "finish_with_error": "finish_with_error",
        },
    )
    .add_conditional_edges(
        "extract_warrants",
        route_after_extract_warrants,
        {
            "next": "integrate",
            "finalize_fallback": "finalize_fallback",
            "finish_with_error": "finish_with_error",
        },
    )
    .add_conditional_edges(
        "integrate",
        route_after_synthesis_step,
        {"next": "add_integrated_rule", "finish_with_error": "finish_with_error"},
    )
    .add_conditional_edges(
        "add_integrated_rule",
        route_round_entry,
        {
            "can_generate_main": "can_generate_main",
            "finalize_fallback": "finalize_fallback",
            "finish_with_error": "finish_with_error",
        },
    )
    .add_edge("generate_final_answer", "finish")
    .add_edge("finish", END)
    .add_edge("finish_with_error", END)
    .compile(name="Dialect MAS")
)
