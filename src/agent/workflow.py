from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from langgraph.graph import END, START, StateGraph

from .schema.state import ArgumentRecord, DefeatRelation
from .schema.types import AgentName, DebateStage
from .edges import (
    route_after_add_integrated_rule,
    route_after_can_generate_main,
    route_after_o_defeat_a,
    route_after_p_counter_b,
    route_after_synthesis_step,
    route_after_thread,
    route_after_validate_b_defeats_a,
    route_after_validate_b_defeats_c,
    route_after_validate_c_defeats_b,
)
from .nodes import (
    add_integrated_rule,
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


@dataclass
class State:
    question: str
    agent1_stance: str
    agent2_stance: str
    max_turns: int = 5
    additional_context: dict[str, Any] = field(default_factory=dict)

    debate_round: int = 1
    learned_findings: list[str] = field(default_factory=list)
    integrated_rules: list[str] = field(default_factory=list)

    # ラウンド上限に達したら debate をスキップして暫定回答を作る。
    finalize_mode: bool = False
    # justified な決着（合意）に至ったか。fallback 暫定回答では False。
    consensus_reached: Optional[bool] = None

    active_agent: AgentName = "AG1"
    current_proponent: AgentName = "AG1"
    current_opponent: AgentName = "AG2"
    debate_stage: DebateStage = "ag1_main_thread"
    turn_count: int = 0

    history: list[ArgumentRecord] = field(default_factory=list)
    dialogue_history: list[dict[str, Any]] = field(default_factory=list)
    defeat_relations: list[DefeatRelation] = field(default_factory=list)

    current_argument: Optional[ArgumentRecord] = None
    ag1_main_argument: Optional[ArgumentRecord] = None
    ag2_main_argument: Optional[ArgumentRecord] = None
    ag1_current_main_id: Optional[str] = None
    ag2_current_main_id: Optional[str] = None
    main_argument_available: Optional[bool] = None
    main_argument_unavailable_reason: Optional[str] = None
    ag1_thread_status: Optional[str] = None
    ag2_thread_status: Optional[str] = None
    current_thread_status: Optional[str] = None

    b_argument: Optional[ArgumentRecord] = None
    c_argument: Optional[ArgumentRecord] = None
    d_argument: Optional[ArgumentRecord] = None
    b_argument_id: Optional[str] = None
    c_argument_id: Optional[str] = None
    d_argument_id: Optional[str] = None
    b_defeats_a: Optional[bool] = None
    c_defeats_b: Optional[bool] = None
    b_defeats_c: Optional[bool] = None
    c_strictly_defeats_b: Optional[bool] = None

    # Compatibility fields used by def.py and existing result consumers.
    ag1_rejection_rebuttal: Optional[str] = None
    ag1_pending: bool = False
    ag2_pending: bool = False
    last_can_defeat: Optional[bool] = None
    last_generated_argument: Optional[ArgumentRecord] = None
    last_generated_argument_appended: bool = False
    final_rebuttal: Optional[str] = None

    warrant_result: Optional[str] = None
    generalization_result: Optional[str] = None
    integration_result: Optional[str] = None
    integrated_rule: Optional[str] = None

    justified_argument: Optional[str] = None
    justification_status: Optional[str] = None
    final_answer: Optional[str] = None
    error: Optional[str] = None


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
    .add_node("finish", finish)
    .add_node("finish_with_error", finish_with_error)
    .add_edge(START, "can_generate_main")
    .add_conditional_edges(
        "can_generate_main",
        route_after_can_generate_main,
        {
            "o_defeat_a": "o_defeat_a",
            "finalize_fallback": "finalize_fallback",
            "finish": "finish",
            "finish_with_error": "finish_with_error",
        },
    )
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
            "extract_warrants": "extract_warrants",
            "generate_final_answer": "generate_final_answer",
            "finish": "finish",
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
        route_after_add_integrated_rule,
        {
            "can_generate_main": "can_generate_main",
            "finish": "finish",
            "finish_with_error": "finish_with_error",
        },
    )
    .add_edge("generate_final_answer", "finish")
    .add_edge("finish", END)
    .add_edge("finish_with_error", END)
    .compile(name="Dialect MAS")
)
