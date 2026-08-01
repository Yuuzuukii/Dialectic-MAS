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
from types import SimpleNamespace
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from .arguments import generate_final_answer as _generate_final_answer
from .arguments import generate_integration as _generate_integration
from .edges import _int_env, _optional_int_env
from .llm import chat_structured, chat_text
from .nodes import extract_integrated_rule
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
    # schema/no_schemaと手法間でターン数（主張・反論の機会の総数）を揃えて比較する場合の、
    # 絶対ターン数上限。None（既定）なら無効で、上記の max_turns（ラウンド数）だけで
    # 従来通り動く。設定すると、AG1・AG2どちらのターンの後でも、この上限に達した時点で
    # ラウンドの途中でも即座に judge へ進む（片方の発言だけを1ターンと数える）。
    max_dialogue_turns: int | None = _optional_int_env("MAX_DIALOGUE_TURNS")
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
    # False（既定）: 純粋なMAD（勝者を決めるjudgeによる最終回答）。統合プロセスの重要性検証で
    # ベースラインとして使う。True: judgeの代わりに、schema/no_schemaと共通の統合プロンプト
    # （止揚による統合）で最終回答を作る。議論過程の重要性検証で他手法と揃えて使う。
    use_synthesis: bool = False
    integration_result: str | None = None
    integrated_rule: str | None = None


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


def _dialogue_turn_budget_exceeded(state: MADState) -> bool:
    """絶対ターン数上限（`max_dialogue_turns`）に既に達しているか（未設定なら常に False）."""
    if state.max_dialogue_turns is None:
        return False
    return len(state.dialogue_history) >= state.max_dialogue_turns


def _after_debate(state: MADState) -> str:
    """討議終了後の遷移先: use_synthesis に応じて judge か integrate かを選ぶ."""
    return "integrate" if state.use_synthesis else "judge"


def route_after_ag1_turn(state: MADState) -> str:
    """AG1 の手番直後の遷移先を決める.

    `max_dialogue_turns`（全手法共通の絶対ターン数上限）が設定されている場合だけ、
    ラウンドの途中（AG2 の番の前）でもここで打ち切って judge/integrate へ進む。
    schema/no_schema とターン数（＝主張・反論の機会の総数）を揃えて比較したいときに使う。
    未設定なら常に ag2_turn へ進み、既存の round ベースの挙動と完全に同じ。
    """
    if _dialogue_turn_budget_exceeded(state):
        return _after_debate(state)
    return "ag2_turn"


def route_after_ag2_turn(state: MADState) -> str:
    """次の分岐を決める.

    - `max_dialogue_turns`（絶対ターン数上限）に達したら judge/integrate へ。
    - ラウンド上限 (max_turns) に達したら judge/integrate へ（ハード上限）。
    - 上限未満でも、その1ラウンドで両者とも新しい反論を出せなかった（収束した）場合は
      早期に judge/integrate へ進む。これにより max_turns は schema/no_schema の
      max_attack_attempts と同じ「上限」の意味になる。
    """
    if _dialogue_turn_budget_exceeded(state):
        return _after_debate(state)
    completed_rounds = state.round - 1
    if completed_rounds >= state.max_turns:
        return _after_debate(state)
    if state.ag1_has_new is False and state.ag2_has_new is False:
        return _after_debate(state)
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


def _last_argument_by(state: MADState, agent: AgentName) -> str:
    for turn in reversed(state.dialogue_history):
        if turn.get("agent") == agent:
            return str(turn.get("argument", ""))
    return ""


async def integrate(state: MADState) -> dict[str, Any]:
    """止揚による統合（judgeで勝者を決めない代替パス）.

    schema/no_schemaと共通の統合プロンプトで、両サイド最新の主張を汎化した上で
    1つの再利用可能ルールにまとめる。弁証法プロトコルのような形式的な warrant
    抽出は無いため、各サイドの最新の主張を warrant の代わりとして渡す。
    """
    warrant_result = json.dumps(
        {
            "Argument1": {"agent": "AG1", "warrant": _last_argument_by(state, "AG1")},
            "Argument2": {"agent": "AG2", "warrant": _last_argument_by(state, "AG2")},
        },
        ensure_ascii=False,
    )
    synthesis_state = SimpleNamespace(
        warrant_result=warrant_result,
        agent1_stance=state.agent1_stance,
        agent2_stance=state.agent2_stance,
        output_mode="no_schema",
    )
    output = await _generate_integration(synthesis_state)
    response = json.dumps(
        output.model_dump(exclude_none=True), ensure_ascii=False, indent=2
    )
    rule = extract_integrated_rule(response)
    return {"integration_result": response, "integrated_rule": rule}


async def generate_final_answer(state: MADState) -> dict[str, Any]:
    """統合ルールを踏まえて最終回答を生成する（schema/no_schemaの合意なし時と共通のプロンプト）."""
    last_argument = state.dialogue_history[-1]["argument"] if state.dialogue_history else None
    synthesis_state = SimpleNamespace(
        justified_argument=last_argument,
        dialogue_history=state.dialogue_history,
        integrated_rules=[state.integrated_rule] if state.integrated_rule else [],
        consensus_reached=False,
        question=state.question,
        agent1_stance=state.agent1_stance,
        agent2_stance=state.agent2_stance,
    )
    answer = await _generate_final_answer(synthesis_state)
    return {"final_answer": answer.strip()}


graph_mad = (
    StateGraph(MADState)
    .add_node("ag1_turn", ag1_turn)
    .add_node("ag2_turn", ag2_turn)
    .add_node("judge", judge)
    .add_node("integrate", integrate)
    .add_node("generate_final_answer", generate_final_answer)
    .add_edge(START, "ag1_turn")
    .add_conditional_edges(
        "ag1_turn",
        route_after_ag1_turn,
        {"ag2_turn": "ag2_turn", "judge": "judge", "integrate": "integrate"},
    )
    .add_conditional_edges(
        "ag2_turn",
        route_after_ag2_turn,
        {"ag1_turn": "ag1_turn", "judge": "judge", "integrate": "integrate"},
    )
    .add_edge("judge", END)
    .add_edge("integrate", "generate_final_answer")
    .add_edge("generate_final_answer", END)
    .compile(name="MAD")
)
