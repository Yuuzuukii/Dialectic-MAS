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
from pydantic import BaseModel, Field

from .edges import _int_env
from .llm import chat_structured, chat_text
from .prompts import PromptTemplates, agent_system
from .schema.types import AgentName


class DebateTurn(BaseModel):
    """1 ターン分の発話と、新しい論点（反論）を出せたかの自己申告フラグ."""

    argument: str = Field(description="Your argument for your stance this turn.")
    has_new_point: bool = Field(
        description=(
            "True if this turn introduces a genuinely new argument or rebuttal not already "
            "made earlier in the debate. False if you have nothing substantively new to add "
            "beyond what has already been said."
        )
    )


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
    # 早期停止用: 各エージェントが「今ラウンドで新しい論点（反論）を出せたか」の自己申告。
    # 1ラウンドで両者とも False（＝新しい反論なし＝収束）なら max_turns 未満でも終了する。
    ag1_has_new: bool | None = None
    ag2_has_new: bool | None = None


def _stance(state: MADState, agent: AgentName) -> str:
    return state.agent1_stance if agent == "AG1" else state.agent2_stance


# ラウンド2以降の指示に付ける early-stop の逃げ道（escape hatch）。
_NOVELTY_HINT = (
    " If you still have a genuinely new rebuttal or argument, make it and set has_new_point=true."
    " If you have nothing substantively new to add beyond the dialogue so far, say so briefly and"
    " set has_new_point=false."
)


def _round_instruction(state: MADState, agent: AgentName) -> str:
    if state.round == 1:
        if agent == "AG1":
            return f"Question: {state.question}\n\nState your initial argument for your stance."
        return "Considering AG1's argument above, argue against it and state your argument for your stance."
    if agent == "AG1":
        return (
            "Considering AG2's latest argument above, argue against it and give your updated"
            " argument for your stance." + _NOVELTY_HINT
        )
    return (
        "Considering AG1's latest argument above, argue against it and give your updated"
        " argument for your stance." + _NOVELTY_HINT
    )


async def _agent_turn(state: MADState, agent: AgentName, instruction: str) -> DebateTurn:
    system = agent_system(_stance(state, agent), agent, PromptTemplates.MAD_TURN_SYSTEM)
    messages = [
        SystemMessage(content=system),
        *state.history,
        HumanMessage(content=instruction),
    ]
    return await chat_structured(messages, DebateTurn)


async def ag1_turn(state: MADState) -> dict[str, Any]:
    """AG1 が、これまでの対話履歴（AG2 の直前の反論を含む）を見て主張を生成する."""
    instruction = _round_instruction(state, "AG1")
    turn = await _agent_turn(state, "AG1", instruction)
    text = turn.argument.strip()
    # 初回ラウンドの主張は定義上「新しい」ため True 固定。以降は自己申告に従う。
    has_new = True if state.round == 1 else turn.has_new_point
    return {
        "history": [*state.history, HumanMessage(content=instruction), AIMessage(content=text, name="AG1")],
        "dialogue_history": [
            *state.dialogue_history,
            {"agent": "AG1", "round": state.round, "argument": text, "has_new_point": has_new},
        ],
        "ag1_has_new": has_new,
    }


async def ag2_turn(state: MADState) -> dict[str, Any]:
    """AG2 が、AG1 の今ラウンドの発言を含む対話履歴を見て主張を生成する."""
    instruction = _round_instruction(state, "AG2")
    turn = await _agent_turn(state, "AG2", instruction)
    text = turn.argument.strip()
    has_new = True if state.round == 1 else turn.has_new_point
    return {
        "history": [*state.history, HumanMessage(content=instruction), AIMessage(content=text, name="AG2")],
        "dialogue_history": [
            *state.dialogue_history,
            {"agent": "AG2", "round": state.round, "argument": text, "has_new_point": has_new},
        ],
        "round": state.round + 1,
        "ag2_has_new": has_new,
    }


def route_after_ag2_turn(state: MADState) -> str:
    """次の分岐を決める.

    - ラウンド上限 (max_turns) に達したら judge へ（ハード上限）。
    - 上限未満でも、その1ラウンドで両者とも新しい反論を出せなかった（収束した）場合は
      早期に judge へ進む。これにより max_turns は schema/no_schema の
      max_attack_attempts と同じ「上限」の意味になる。
    """
    completed_rounds = state.round - 1
    if completed_rounds >= state.max_turns:
        return "judge"
    if state.ag1_has_new is False and state.ag2_has_new is False:
        return "judge"
    return "ag1_turn"


async def judge(state: MADState) -> dict[str, Any]:
    """ラウンド上限到達後、AG1/AG2 のいずれでもない独立した judge が対話全体から最終回答を作る."""
    user = PromptTemplates.MAD_JUDGE_USER.format(
        question=state.question,
        dialogue_history=json.dumps(state.dialogue_history, ensure_ascii=False, indent=2),
    ).strip()
    answer = await chat_text(
        [SystemMessage(content=PromptTemplates.MAD_JUDGE_SYSTEM), HumanMessage(content=user)],
        verbosity="high",
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
