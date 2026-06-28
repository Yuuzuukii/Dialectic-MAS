"""議論ワークフローの状態定義と LangGraph グラフの構築."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from langchain_core.messages import BaseMessage
from langgraph.graph import END, START, StateGraph

from .edges import (
    _int_env,
    route_after_can_generate_main,
    route_after_o_defeat_a,
    route_after_p_counter_b,
    route_after_synthesis_step,
    route_after_thread,
    route_after_validate_b_defeats_a,
    route_after_validate_b_defeats_c,
    route_after_validate_c_defeats_b,
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
    generalize,
    generate_final_answer,
    integrate,
    o_defeat_a,
    p_counter_b,
    route_after_thread_node,
    validate_b_defeats_a,
    validate_b_defeats_c,
    validate_c_defeats_b,
)
from .schema.state import ArgumentRecord, DefeatRelation
from .schema.types import AgentName, DebateStage


@dataclass
class State:
    """議論グラフ全体で共有される可変状態."""

    question: str
    agent1_stance: str
    agent2_stance: str
    # 議論ラウンド（debate_round）の上限。環境変数 MAX_TURNS で上書きできる。
    max_turns: int = _int_env("MAX_TURNS", 5)
    # 1ラウンド・1 proponent あたりの main argument 試行回数の上限（安全装置）。
    # 環境変数 MAX_MAIN_ARGUMENT_ATTEMPTS で上書きできる。
    max_main_argument_attempts: int = _int_env("MAX_MAIN_ARGUMENT_ATTEMPTS", 5)
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
    # 同一ラウンド・同一 proponent が main argument を試行した回数（安全装置）。
    main_attempt_count: int = 0

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
    current_thread_status: str | None = None

    b_argument: ArgumentRecord | None = None
    c_argument: ArgumentRecord | None = None
    b_argument_id: str | None = None
    c_argument_id: str | None = None
    b_defeats_a: bool | None = None
    c_defeats_b: bool | None = None
    b_defeats_c: bool | None = None
    c_strictly_defeats_b: bool | None = None

    # Compatibility fields used by def.py and existing result consumers.
    ag1_rejection_rebuttal: str | None = None
    ag1_pending: bool = False
    ag2_pending: bool = False
    last_can_defeat: bool | None = None
    last_generated_argument: ArgumentRecord | None = None
    last_generated_argument_appended: bool = False
    final_rebuttal: str | None = None

    warrant_result: str | None = None
    generalization_result: str | None = None
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
    .add_node("o_defeat_a", o_defeat_a)
    .add_node("validate_b_defeats_a", validate_b_defeats_a)
    .add_node("p_counter_b", p_counter_b)
    .add_node("validate_c_defeats_b", validate_c_defeats_b)
    .add_node("validate_b_defeats_c", validate_b_defeats_c)
    .add_node("route_after_thread", route_after_thread_node)
    .add_node("extract_warrants", extract_warrants)
    .add_node("generalize", generalize)
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
            "o_defeat_a": "o_defeat_a",
            "advance_to_ag2": "advance_to_ag2",
            "extract_warrants": "extract_warrants",
            "finish_with_error": "finish_with_error",
        },
    )
    .add_edge("advance_to_ag2", "can_generate_main")
    .add_edge("finalize_fallback", "generate_final_answer")
    .add_conditional_edges(
        "o_defeat_a",
        route_after_o_defeat_a,
        {
            "validate_b_defeats_a": "validate_b_defeats_a",
            "generate_final_answer": "generate_final_answer",
            "finish": "finish",
            "finish_with_error": "finish_with_error",
        },
    )
    .add_conditional_edges(
        "validate_b_defeats_a",
        route_after_validate_b_defeats_a,
        {
            "p_counter_b": "p_counter_b",
            "generate_final_answer": "generate_final_answer",
            "finish_with_error": "finish_with_error",
        },
    )
    .add_conditional_edges(
        "p_counter_b",
        route_after_p_counter_b,
        {
            "validate_c_defeats_b": "validate_c_defeats_b",
            "route_after_thread": "route_after_thread",
            "finish_with_error": "finish_with_error",
        },
    )
    .add_conditional_edges(
        "validate_c_defeats_b",
        route_after_validate_c_defeats_b,
        {
            "validate_b_defeats_c": "validate_b_defeats_c",
            "route_after_thread": "route_after_thread",
            "finish_with_error": "finish_with_error",
        },
    )
    .add_conditional_edges(
        "validate_b_defeats_c",
        route_after_validate_b_defeats_c,
        {
            "route_after_thread": "route_after_thread",
            "finish_with_error": "finish_with_error",
        },
    )
    .add_conditional_edges(
        "route_after_thread",
        route_after_thread,
        {
            "can_generate_main": "can_generate_main",
            "advance_to_ag2": "advance_to_ag2",
            "extract_warrants": "extract_warrants",
            "generate_final_answer": "generate_final_answer",
            "finish_with_error": "finish_with_error",
        },
    )
    .add_conditional_edges(
        "extract_warrants",
        route_after_synthesis_step,
        {"next": "generalize", "finish_with_error": "finish_with_error"},
    )
    .add_conditional_edges(
        "generalize",
        route_after_synthesis_step,
        {"next": "integrate", "finish_with_error": "finish_with_error"},
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
