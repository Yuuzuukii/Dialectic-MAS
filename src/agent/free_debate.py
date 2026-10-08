"""弁証法プロトコルを使わない自由討議ベースライン.

AG1・AG2 が同一ラウンド内で交互に発言する（AG2 は AG1 のそのラウンドの発言を見た上で
発言する）固定ラウンド数の討議。ラウンド上限に達したら、schema/no_schemaと共通の統合
プロンプトで止揚による統合を行い、その統合ルールを踏まえて最終回答を生成する。

既存の弁証法グラフ（workflow.py）とは独立した、rebut/undercut/justified 等の概念を
一切持たない最小限のグラフ。詳細は docs/free_debate_protocol_plan.md を参照。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from .edges import _int_env, _optional_int_env
from .final_answer import (
    PATH_DIALOGUE_ONLY,
    PATH_INTEGRATED,
    answer_from_materials,
    integrate_positions,
    last_position,
)
from .llm import chat_structured
from .prompts import PromptTemplates, agent_system
from .schema.types import AgentName


class DebateTurn(BaseModel):
    """1 ターン分の発話と、新しい論点を出せたかの自己申告フラグ."""

    argument: str = Field(description="Your argument for your stance this turn.")
    has_new_point: bool = Field(
        description=(
            "True if this turn introduces a genuinely new argument or rebuttal not already "
            "made earlier in the debate. False if you have nothing substantively new to add "
            "beyond what has already been said."
        )
    )


@dataclass
class FreeDebateState:
    """自由討議グラフ全体で共有される可変状態."""

    question: str
    agent1_stance: str
    agent2_stance: str
    max_turns: int = _int_env("MAX_TURNS", 5)
    # schema/no_schemaと手法間でターン数（主張・反論の機会の総数）を揃えて比較する場合の、
    # 絶対ターン数上限。None（既定）なら無効で、上記の max_turns（ラウンド数）だけで
    # 従来通り動く。設定すると、AG1・AG2どちらのターンの後でも、この上限に達した時点で
    # ラウンドの途中でも即座に最終回答生成へ進む（片方の発言だけを1ターンと数える）。
    max_dialogue_turns: int | None = _optional_int_env("MAX_DIALOGUE_TURNS")
    round: int = 1
    # LLM 再送用の共有履歴。HumanMessage(指示) と AIMessage(発話, name=agent) の対で増えていく。
    history: list[BaseMessage] = field(default_factory=list)
    # ログ用の対話履歴（schema/no_schemaの dialogue_history と同じ {agent, argument} 形式）。
    dialogue_history: list[dict[str, Any]] = field(default_factory=list)
    final_answer: str | None = None
    # 早期停止用: 各エージェントが「今ラウンドで新しい論点を出せたか」の自己申告。
    # 1ラウンドで両者とも False（＝新しい点なし＝収束）なら max_turns 未満でも終了する。
    ag1_has_new: bool | None = None
    ag2_has_new: bool | None = None
    integration_result: str | None = None
    integrated_rule: str | None = None
    # 最終回答の材料にした統合案と、最終回答の作り方（final_answer.py）。
    integrated_proposal: str | None = None
    finalization_path: str | None = None


def _stance(state: FreeDebateState, agent: AgentName) -> str:
    return state.agent1_stance if agent == "AG1" else state.agent2_stance


# ラウンド2以降の指示に付ける early-stop の逃げ道（escape hatch）。
_NOVELTY_HINT = (
    " Before answering, compare what you plan to say against everything your side has already"
    " said earlier in this debate (earlier arguments and rebuttals alike). If the only thing you"
    " can say substantially restates it — the same facts or reasoning, even if reworded or"
    " reframed — do not resubmit it: say briefly that you have nothing new and set"
    " has_new_point=false. Otherwise, make your new argument or rebuttal and set"
    " has_new_point=true."
)


def _round_instruction(state: FreeDebateState, agent: AgentName) -> str:
    if state.round == 1:
        if agent == "AG1":
            return f"Question: {state.question}\n\nState your initial argument for your stance."
        return "Considering AG1's argument above, state your initial argument for your stance."
    if agent == "AG1":
        return (
            "Considering the dialogue history above, give your updated argument for your stance."
            + _NOVELTY_HINT
        )
    return (
        "Considering the dialogue history above, including AG1's latest argument, give your updated"
        " argument for your stance." + _NOVELTY_HINT
    )


async def _agent_turn(
    state: FreeDebateState, agent: AgentName, instruction: str
) -> DebateTurn:
    system = agent_system(
        _stance(state, agent), agent, PromptTemplates.FREE_DEBATE_TURN_SYSTEM
    )
    messages = [
        SystemMessage(content=system),
        *state.history,
        HumanMessage(content=instruction),
    ]
    return await chat_structured(messages, DebateTurn)


async def ag1_turn(state: FreeDebateState) -> dict[str, Any]:
    """AG1 が、これまでの対話履歴を見て主張を生成する."""
    instruction = _round_instruction(state, "AG1")
    turn = await _agent_turn(state, "AG1", instruction)
    text = turn.argument.strip()
    # 初回ラウンドの主張は定義上「新しい」ため True 固定。以降は自己申告に従う。
    has_new = True if state.round == 1 else turn.has_new_point
    return {
        "history": [
            *state.history,
            HumanMessage(content=instruction),
            AIMessage(content=text, name="AG1"),
        ],
        "dialogue_history": [
            *state.dialogue_history,
            {
                "agent": "AG1",
                "round": state.round,
                "argument": text,
                "has_new_point": has_new,
            },
        ],
        "ag1_has_new": has_new,
    }


async def ag2_turn(state: FreeDebateState) -> dict[str, Any]:
    """AG2 が、AG1 の今ラウンドの発言を含む対話履歴を見て主張を生成する."""
    instruction = _round_instruction(state, "AG2")
    turn = await _agent_turn(state, "AG2", instruction)
    text = turn.argument.strip()
    has_new = True if state.round == 1 else turn.has_new_point
    return {
        "history": [
            *state.history,
            HumanMessage(content=instruction),
            AIMessage(content=text, name="AG2"),
        ],
        "dialogue_history": [
            *state.dialogue_history,
            {
                "agent": "AG2",
                "round": state.round,
                "argument": text,
                "has_new_point": has_new,
            },
        ],
        "round": state.round + 1,
        "ag2_has_new": has_new,
    }


def _dialogue_turn_budget_exceeded(state: FreeDebateState) -> bool:
    """絶対ターン数上限（`max_dialogue_turns`）に既に達しているか（未設定なら常に False）."""
    if state.max_dialogue_turns is None:
        return False
    return len(state.dialogue_history) >= state.max_dialogue_turns


def route_after_ag1_turn(state: FreeDebateState) -> str:
    """AG1 の手番直後の遷移先を決める.

    `max_dialogue_turns`（全手法共通の絶対ターン数上限）が設定されている場合だけ、
    ラウンドの途中（AG2 の番の前）でもここで打ち切って統合ステップへ進む。未設定なら
    常に ag2_turn へ進み、既存の round ベースの挙動と完全に同じ。
    """
    if _dialogue_turn_budget_exceeded(state):
        return "integrate"
    return "ag2_turn"


def route_after_ag2_turn(state: FreeDebateState) -> str:
    """次の分岐を決める.

    - `max_dialogue_turns`（絶対ターン数上限）に達したら統合ステップへ。
    - ラウンド上限 (max_turns) に達したら統合ステップへ（ハード上限）。
    - 上限未満でも、その1ラウンドで両者とも新しい論点を出せなかった（収束した）場合は
      早期に統合ステップへ進む。
    """
    if _dialogue_turn_budget_exceeded(state):
        return "integrate"
    completed_rounds = state.round - 1
    if completed_rounds >= state.max_turns:
        return "integrate"
    if state.ag1_has_new is False and state.ag2_has_new is False:
        return "integrate"
    return "ag1_turn"


async def integrate(state: FreeDebateState) -> dict[str, Any]:
    """各陣営の最後の発言から統合案を作る（schema / no_schema と共通の処理）.

    どちらかの陣営に発言がなければ、統合案は作らない。
    """
    position1 = last_position(state.dialogue_history, "AG1")
    position2 = last_position(state.dialogue_history, "AG2")
    if not (position1 and position2):
        return {"integrated_rule": None}
    rule = await integrate_positions(
        agent1_stance=state.agent1_stance,
        agent2_stance=state.agent2_stance,
        position1=position1,
        position2=position2,
    )
    return {"integrated_rule": rule}


async def generate_final_answer(state: FreeDebateState) -> dict[str, Any]:
    """統合案（あれば）と議論全体から最終回答を生成する（schema / no_schema と共通のプロンプト）."""
    answer = await answer_from_materials(
        question=state.question,
        agent1_stance=state.agent1_stance,
        agent2_stance=state.agent2_stance,
        dialogue_history=state.dialogue_history,
        integrated_proposal=state.integrated_rule,
    )
    return {
        "final_answer": answer,
        "integrated_proposal": state.integrated_rule,
        "finalization_path": PATH_INTEGRATED
        if state.integrated_rule
        else PATH_DIALOGUE_ONLY,
    }


graph_free_debate = (
    StateGraph(FreeDebateState)
    .add_node("ag1_turn", ag1_turn)
    .add_node("ag2_turn", ag2_turn)
    .add_node("integrate", integrate)
    .add_node("generate_final_answer", generate_final_answer)
    .add_edge(START, "ag1_turn")
    .add_conditional_edges(
        "ag1_turn",
        route_after_ag1_turn,
        {"ag2_turn": "ag2_turn", "integrate": "integrate"},
    )
    .add_conditional_edges(
        "ag2_turn",
        route_after_ag2_turn,
        {"ag1_turn": "ag1_turn", "integrate": "integrate"},
    )
    .add_edge("integrate", "generate_final_answer")
    .add_edge("generate_final_answer", END)
    .compile(name="Free Debate")
)
