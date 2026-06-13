"""LLM 生成呼び出しの単一集約点.

各手番（main / attack[defeat,counter] / undercut）と合成（generalize / integrate）、
最終回答（final_answer）の生成を、メッセージ組み立て→LLM 呼び出し→結果整形まで一括で行う。
ノード（nodes.py）はこれらの generate_* を呼ぶだけで、状態の整形に専念する。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, cast

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from .llm import chat_structured, chat_text
from .prompts import (
    ATTACK_SYSTEM,
    PromptTemplates,
    agent_system,
    attack_instruction,
    compose_system,
    main_instruction,
    undercut_instruction,
)
from .schema.llm_outputs import (
    ArgumentBody,
    DefeatingArgumentOutput,
    GeneralizationOutput,
    IntegrationOutput,
    MainArgumentAvailabilityOutput,
    UndercutOutput,
)
from .schema.state import ArgumentRecord
from .schema.types import AgentName


@dataclass
class MainGeneration:
    """主張生成の結果（可否・理由・生成された ArgumentRecord）."""

    available: bool
    reason: str | None
    argument: ArgumentRecord | None


def _stance(state: Any, agent: AgentName) -> str:
    """指定エージェントのスタンス文字列を返す."""
    return cast(str, state.agent1_stance if agent == "AG1" else state.agent2_stance)


def render_history(history: list[ArgumentRecord]) -> list[BaseMessage]:
    """state.history を読み取り専用で受け取り、視点非依存のメッセージ列に変換する.

    各 turn は AIMessage（assistant）とし、`name` に発言者 (AG1/AG2) を載せて区別する。
    content は ArgumentRecord.message_content()（round/phase/agent/attack/status + Argument の JSON）。
    state は一切変更しない（毎回まっさらな新リストを返す）。
    """
    return [
        AIMessage(content=record.message_content(), name=record.agent)
        for record in history
    ]


def build_main_argument_messages(state: Any, agent: AgentName) -> list[BaseMessage]:
    """主張生成用の system/履歴/指示メッセージ列を組み立てる."""
    return [
        SystemMessage(
            content=agent_system(
                _stance(state, agent), agent, PromptTemplates.MAIN_ARGUMENT_SYSTEM
            )
        ),
        *render_history(state.history),
        HumanMessage(content=main_instruction(state)),
    ]


def build_attack_messages(
    state: Any, attacker: AgentName, target: ArgumentRecord, *, purpose: str
) -> list[BaseMessage]:
    """攻撃（defeat/counter）生成用のメッセージ列を組み立てる."""
    return [
        SystemMessage(
            content=agent_system(_stance(state, attacker), attacker, ATTACK_SYSTEM[purpose])
        ),
        *render_history(state.history),
        HumanMessage(content=attack_instruction(purpose, target.id)),
    ]


def build_undercut_messages(
    state: Any, attacker: AgentName, target: ArgumentRecord
) -> list[BaseMessage]:
    """Undercut 生成用のメッセージ列を組み立てる."""
    return [
        SystemMessage(
            content=agent_system(
                _stance(state, attacker), attacker, PromptTemplates.UNDERCUT_SYSTEM
            )
        ),
        *render_history(state.history),
        HumanMessage(content=undercut_instruction(target.id)),
    ]


def argument_body_json(argument: ArgumentBody) -> str:
    """Serialize an ArgumentBody with Conc and Ass derived from its rules."""
    body = argument.model_dump(exclude_none=True)
    rules = body.get("rules", [])
    conclusions: list[str] = []
    assumptions: list[str] = []
    if isinstance(rules, list):
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            consequent = rule.get("consequent")
            if isinstance(consequent, str) and consequent.strip():
                conclusions.append(consequent.strip())
            antecedent = rule.get("antecedent", {})
            if isinstance(antecedent, dict):
                for item in antecedent.get("weak_negation", []) or []:
                    if isinstance(item, str) and item.strip():
                        assumptions.append(item.strip())
    body["Conc"] = conclusions
    body["Ass"] = assumptions
    return json.dumps({"Argument": body}, ensure_ascii=False, indent=2)


async def generate_main(state: Any, agent: AgentName) -> MainGeneration:
    """Proponent の新しい主張 (A) を生成できるか判定し、可能なら ArgumentRecord 化する."""
    messages = build_main_argument_messages(state, agent)
    output = await chat_structured(messages, MainArgumentAvailabilityOutput)
    if output.can_generate != "YES":
        return MainGeneration(available=False, reason=output.reason, argument=None)
    if output.Argument is None:
        return MainGeneration(available=True, reason=output.reason, argument=None)
    argument = ArgumentRecord(
        type="main",
        argument=argument_body_json(output.Argument),
        support=[],
        agent=agent,
        round=state.debate_round,
    )
    return MainGeneration(available=True, reason=None, argument=argument)


async def generate_attack(
    state: Any,
    attacker: AgentName,
    target: ArgumentRecord,
    *,
    purpose: str,
) -> ArgumentRecord | None:
    """攻撃（defeat/counter）主張を LLM 生成し、ArgumentRecord 化する."""
    messages = build_attack_messages(state, attacker, target, purpose=purpose)
    output = await chat_structured(messages, DefeatingArgumentOutput)
    if output.can_defeat != "YES" or output.Argument is None or output.Attack is None:
        return None
    return ArgumentRecord(
        type="counter" if purpose == "counter" else "defeat",
        argument=argument_body_json(output.Argument),
        support=[],
        agent=attacker,
        attack=output.Attack.method,
        target_id=target.id,
        target_field=output.Attack.target.field,
        target_statement=output.Attack.target.statement,
        round=getattr(state, "debate_round", 1),
    )


async def generate_undercut(
    state: Any,
    attacker: AgentName,
    target: ArgumentRecord,
) -> ArgumentRecord | None:
    """対象の仮定（Ass）を狙う undercut 主張を LLM 生成し、ArgumentRecord 化する."""
    if not target.assumptions:
        return None
    messages = build_undercut_messages(state, attacker, target)
    output = await chat_structured(messages, UndercutOutput)
    if output.can_undercut != "YES" or output.Argument is None:
        return None
    return ArgumentRecord(
        type="defeat",
        argument=argument_body_json(output.Argument),
        support=[],
        agent=attacker,
        attack="undercut",
        target_id=target.id,
        target_field="Ass",
        round=getattr(state, "debate_round", 1),
    )


async def generate_generalization(state: Any) -> GeneralizationOutput:
    """両エージェントの warrant を汎化し、再利用可能な基準を導出する."""
    dialogue_history = json.dumps(state.dialogue_history, ensure_ascii=False, indent=2)
    system = compose_system(
        state.agent1_stance, PromptTemplates.GENERALIZATION_SYSTEM
    )
    user = f"## Warrants\n{state.warrant_result}\n\n## Dialogue History\n{dialogue_history}"
    return await chat_structured(
        [SystemMessage(content=system), HumanMessage(content=user)],
        GeneralizationOutput,
    )


async def generate_integration(state: Any) -> IntegrationOutput:
    """汎化された基準を一つの統合ルールにまとめる."""
    system = compose_system(state.agent1_stance, PromptTemplates.INTEGRATION_SYSTEM)
    user = f"{state.warrant_result}\n\n{state.generalization_result}"
    return await chat_structured(
        [SystemMessage(content=system), HumanMessage(content=user)],
        IntegrationOutput,
    )


async def generate_final_answer(state: Any) -> str:
    """対話履歴を踏まえて自然文回答を生成する.

    通常は justified な主張から作る。合意に至らず暫定回答を作る場合
    (consensus_reached is False) は、合意なしであることを明示する専用プロンプトを使う。
    """
    justified = state.justified_argument
    status = state.justification_status or ""
    stance = state.agent2_stance if status.startswith("ag2") else state.agent1_stance
    dialogue_history = json.dumps(state.dialogue_history, ensure_ascii=False, indent=2)

    if state.consensus_reached is False:
        integrated_rules = (
            "\n".join(f"- {rule}" for rule in state.integrated_rules) or "(none)"
        )
        system = compose_system(
            stance, PromptTemplates.FINAL_ANSWER_NO_CONSENSUS_SYSTEM
        )
        user = PromptTemplates.FINAL_ANSWER_NO_CONSENSUS_USER.format(
            question=state.question,
            integrated_rules=integrated_rules,
            dialogue_history=dialogue_history,
            justified_argument=justified,
        ).strip()
    else:
        system = compose_system(stance, PromptTemplates.FINAL_ANSWER_SYSTEM)
        user = PromptTemplates.FINAL_ANSWER_USER.format(
            question=state.question,
            dialogue_history=dialogue_history,
            justified_argument=justified,
        ).strip()

    return await chat_text(
        [SystemMessage(content=system), HumanMessage(content=user)],
        model=os.getenv("MODEL", "gpt-5-mini"),
    )
