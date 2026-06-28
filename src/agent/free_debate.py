"""弁証法プロトコルを使わない自由討議ベースライン.

AG1・AG2 が同一ラウンド内で交互に発言する（AG2 は AG1 のそのラウンドの発言を見た上で
発言する）固定ラウンド数の討議。ラウンド上限に達したら両者の発言を統合し、その統合結果
から最終回答を生成する。

既存の弁証法グラフ（workflow.py）とは独立した、rebut/undercut/justified 等の概念を
一切持たない最小限のグラフ。詳細は docs/free_debate_protocol_plan.md を参照。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph

from .edges import _int_env
from .llm import chat_text
from .prompts import PromptTemplates, agent_system
from .schema.types import AgentName


@dataclass
class FreeDebateState:
    """自由討議グラフ全体で共有される可変状態."""

    question: str
    agent1_stance: str
    agent2_stance: str
    max_turns: int = _int_env("MAX_TURNS", 5)
    round: int = 1
    # LLM 再送用の共有履歴。HumanMessage(指示) と AIMessage(発話, name=agent) の対で増えていく。
    history: list[BaseMessage] = field(default_factory=list)
    # ログ用の対話履歴（schema/no_schemaの dialogue_history と同じ {agent, argument} 形式）。
    dialogue_history: list[dict[str, Any]] = field(default_factory=list)
    # ラウンド上限後、AG1 が両者の発言から作る短い統合サマリー。
    integrated_summary: str | None = None
    final_answer: str | None = None


def _stance(state: FreeDebateState, agent: AgentName) -> str:
    return state.agent1_stance if agent == "AG1" else state.agent2_stance


def _round_instruction(state: FreeDebateState, agent: AgentName) -> str:
    if state.round == 1:
        if agent == "AG1":
            return f"Question: {state.question}\n\nState your initial argument for your stance."
        return "Considering AG1's argument above, state your initial argument for your stance."
    if agent == "AG1":
        return "Considering the dialogue history above, give your updated argument for your stance."
    return "Considering the dialogue history above, including AG1's latest argument, give your updated argument for your stance."


async def _agent_turn(state: FreeDebateState, agent: AgentName, instruction: str) -> str:
    system = agent_system(_stance(state, agent), agent, PromptTemplates.FREE_DEBATE_TURN_SYSTEM)
    messages = [
        SystemMessage(content=system),
        *state.history,
        HumanMessage(content=instruction),
    ]
    return await chat_text(messages)


async def ag1_turn(state: FreeDebateState) -> dict[str, Any]:
    """AG1 が、これまでの対話履歴を見て主張を生成する."""
    instruction = _round_instruction(state, "AG1")
    text = (await _agent_turn(state, "AG1", instruction)).strip()
    return {
        "history": [*state.history, HumanMessage(content=instruction), AIMessage(content=text, name="AG1")],
        "dialogue_history": [*state.dialogue_history, {"agent": "AG1", "round": state.round, "argument": text}],
    }


async def ag2_turn(state: FreeDebateState) -> dict[str, Any]:
    """AG2 が、AG1 の今ラウンドの発言を含む対話履歴を見て主張を生成する."""
    instruction = _round_instruction(state, "AG2")
    text = (await _agent_turn(state, "AG2", instruction)).strip()
    return {
        "history": [*state.history, HumanMessage(content=instruction), AIMessage(content=text, name="AG2")],
        "dialogue_history": [*state.dialogue_history, {"agent": "AG2", "round": state.round, "argument": text}],
        "round": state.round + 1,
    }


def route_after_ag2_turn(state: FreeDebateState) -> str:
    """ラウンド上限に達していなければ次ラウンド(AG1)へ、達していれば統合へ進む."""
    completed_rounds = state.round - 1
    if completed_rounds < state.max_turns:
        return "ag1_turn"
    return "integrate"


async def integrate(state: FreeDebateState) -> dict[str, Any]:
    """ラウンド上限到達後、AG1 が両者の発言を踏まえて短い統合サマリーを作る."""
    system = PromptTemplates.FREE_DEBATE_INTEGRATION_SYSTEM.format(stance=state.agent1_stance)
    user = PromptTemplates.FREE_DEBATE_INTEGRATION_USER.format(
        question=state.question,
        dialogue_history=json.dumps(state.dialogue_history, ensure_ascii=False, indent=2),
    ).strip()
    summary = await chat_text([SystemMessage(content=system), HumanMessage(content=user)])
    return {"integrated_summary": summary.strip()}


async def generate_final_answer(state: FreeDebateState) -> dict[str, Any]:
    """統合サマリーと対話履歴全体から最終回答を生成する."""
    system = PromptTemplates.FREE_DEBATE_FINAL_ANSWER_SYSTEM
    user = PromptTemplates.FREE_DEBATE_FINAL_ANSWER_USER.format(
        question=state.question,
        integrated_summary=state.integrated_summary or "(none)",
        dialogue_history=json.dumps(state.dialogue_history, ensure_ascii=False, indent=2),
    ).strip()
    answer = await chat_text([SystemMessage(content=system), HumanMessage(content=user)])
    return {"final_answer": answer.strip()}


graph_free_debate = (
    StateGraph(FreeDebateState)
    .add_node("ag1_turn", ag1_turn)
    .add_node("ag2_turn", ag2_turn)
    .add_node("integrate", integrate)
    .add_node("generate_final_answer", generate_final_answer)
    .add_edge(START, "ag1_turn")
    .add_edge("ag1_turn", "ag2_turn")
    .add_conditional_edges(
        "ag2_turn",
        route_after_ag2_turn,
        {"ag1_turn": "ag1_turn", "integrate": "integrate"},
    )
    .add_edge("integrate", "generate_final_answer")
    .add_edge("generate_final_answer", END)
    .compile(name="Free Debate")
)
