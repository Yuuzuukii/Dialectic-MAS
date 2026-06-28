"""MAD (Multi-Agent Debate) ベースライン.

free_debate.py と同じく弁証法プロトコル（undercut/justified 等の ASPIC+ 概念）は持ち込まない。
各ターンの指示文で「相手の直前の主張に argue against せよ」と一言伝えるだけで、反論の手順
（どの前提を否定するか等）を細かく規定しない点が free_debate との違い（Du et al. 流の相互
反論ディベート）。

AG1・AG2 が同一ラウンド内で交互に発言する（AG2 は AG1 のそのラウンドの発言を見て反論する）
固定ラウンド数の討議。ラウンド上限に達したら、AG1/AG2 のいずれでもない独立した judge が
対話全体から最終回答を作る（free_debate の AG1 による統合 + 最終回答の2段とは異なり、
judge による単一の判定で完結する）。詳細は docs/free_debate_protocol_plan.md を参照。
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
class MADState:
    """MAD グラフ全体で共有される可変状態."""

    question: str
    agent1_stance: str
    agent2_stance: str
    max_turns: int = _int_env("MAX_TURNS", 5)
    round: int = 1
    # LLM 再送用の共有履歴。HumanMessage(指示) と AIMessage(発話, name=agent) の対で増えていく。
    history: list[BaseMessage] = field(default_factory=list)
    # ログ用の対話履歴（schema/no_schema/free_debate の dialogue_history と同じ {agent, argument} 形式）。
    dialogue_history: list[dict[str, Any]] = field(default_factory=list)
    final_answer: str | None = None


def _stance(state: MADState, agent: AgentName) -> str:
    return state.agent1_stance if agent == "AG1" else state.agent2_stance


def _round_instruction(state: MADState, agent: AgentName) -> str:
    if state.round == 1:
        if agent == "AG1":
            return f"Question: {state.question}\n\nState your initial argument for your stance."
        return "Considering AG1's argument above, argue against it and state your argument for your stance."
    if agent == "AG1":
        return "Considering AG2's latest argument above, argue against it and give your updated argument for your stance."
    return "Considering AG1's latest argument above, argue against it and give your updated argument for your stance."


async def _agent_turn(state: MADState, agent: AgentName, instruction: str) -> str:
    system = agent_system(_stance(state, agent), agent, PromptTemplates.MAD_TURN_SYSTEM)
    messages = [
        SystemMessage(content=system),
        *state.history,
        HumanMessage(content=instruction),
    ]
    return await chat_text(messages)


async def ag1_turn(state: MADState) -> dict[str, Any]:
    """AG1 が、これまでの対話履歴（AG2 の直前の反論を含む）を見て主張を生成する."""
    instruction = _round_instruction(state, "AG1")
    text = (await _agent_turn(state, "AG1", instruction)).strip()
    return {
        "history": [*state.history, HumanMessage(content=instruction), AIMessage(content=text, name="AG1")],
        "dialogue_history": [*state.dialogue_history, {"agent": "AG1", "round": state.round, "argument": text}],
    }


async def ag2_turn(state: MADState) -> dict[str, Any]:
    """AG2 が、AG1 の今ラウンドの発言を含む対話履歴を見て主張を生成する."""
    instruction = _round_instruction(state, "AG2")
    text = (await _agent_turn(state, "AG2", instruction)).strip()
    return {
        "history": [*state.history, HumanMessage(content=instruction), AIMessage(content=text, name="AG2")],
        "dialogue_history": [*state.dialogue_history, {"agent": "AG2", "round": state.round, "argument": text}],
        "round": state.round + 1,
    }


def route_after_ag2_turn(state: MADState) -> str:
    """ラウンド上限に達していなければ次ラウンド(AG1)へ、達していれば judge へ進む."""
    completed_rounds = state.round - 1
    if completed_rounds < state.max_turns:
        return "ag1_turn"
    return "judge"


async def judge(state: MADState) -> dict[str, Any]:
    """ラウンド上限到達後、AG1/AG2 のいずれでもない独立した judge が対話全体から最終回答を作る."""
    user = PromptTemplates.MAD_JUDGE_USER.format(
        question=state.question,
        dialogue_history=json.dumps(state.dialogue_history, ensure_ascii=False, indent=2),
    ).strip()
    answer = await chat_text(
        [SystemMessage(content=PromptTemplates.MAD_JUDGE_SYSTEM), HumanMessage(content=user)]
    )
    return {"final_answer": answer.strip()}


graph_mad = (
    StateGraph(MADState)
    .add_node("ag1_turn", ag1_turn)
    .add_node("ag2_turn", ag2_turn)
    .add_node("judge", judge)
    .add_edge(START, "ag1_turn")
    .add_edge("ag1_turn", "ag2_turn")
    .add_conditional_edges(
        "ag2_turn",
        route_after_ag2_turn,
        {"ag1_turn": "ag1_turn", "judge": "judge"},
    )
    .add_edge("judge", END)
    .compile(name="MAD")
)
