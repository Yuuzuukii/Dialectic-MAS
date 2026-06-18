"""LLM 生成呼び出しの単一集約点.

各手番（main / attack[defeat,counter] / undercut）と合成（generalize / integrate）、
最終回答（final_answer）の生成を、メッセージ組み立て→LLM 呼び出し→結果整形まで一括で行う。
ノード（nodes.py）はこれらの generate_* を呼ぶだけで、状態の整形に専念する。

`_output_mode(state)` で schema / no_schema を切り替える。両条件とも with_structured_output
による構造化出力を使うが、no_schema では Argument 本体（ArgumentBody の rules/Conc/Ass）の
スキーマを取り除き、自由な natural-language テキストとして出力させる。can_generate /
can_defeat / can_undercut の可否判定と Attack（rebut/undercut + target）のメタデータは、
弁証法的な状態遷移を機械的に決定するために両条件で構造化出力のまま保持する。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, cast

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from .llm import chat_structured, chat_text
from .prompts import (
    PromptTemplates,
    agent_system,
    attack_instruction,
    compose_system,
    generalization_instruction,
    integration_instruction,
    main_instruction,
    synthesis_system,
    undercut_instruction,
)
from .schema.llm_outputs import (
    ArgumentBody,
    DefeatingArgumentOutput,
    DefeatingArgumentOutputFree,
    GeneralizationOutput,
    GeneralizationOutputFree,
    IntegrationOutput,
    IntegrationOutputFree,
    MainArgumentAvailabilityOutput,
    MainArgumentAvailabilityOutputFree,
    UndercutOutput,
    UndercutOutputFree,
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


def _output_mode(state: Any) -> str:
    """state.output_mode を返す（未設定なら既定の "schema"）."""
    return cast(str, getattr(state, "output_mode", "schema"))


def argument_message_content(record: ArgumentRecord) -> str:
    """LLM 履歴の AIMessage に入れる Argument 本体だけを返す."""
    body = record.body
    if body:
        return json.dumps(body, ensure_ascii=False, indent=2)
    return record.argument


def render_history(history: list[Any]) -> list[BaseMessage]:
    """state.history を読み取り専用で受け取り、LLM 用メッセージ列に変換する.

    新設計では state.history は BaseMessage のリスト。古いテストや移行中の呼び出しで
    ArgumentRecord が渡された場合だけ、Argument 本体のみの AIMessage として互換変換する。
    """
    messages: list[BaseMessage] = []
    for item in history:
        if isinstance(item, BaseMessage):
            messages.append(item)
        elif isinstance(item, ArgumentRecord):
            messages.append(
                AIMessage(content=argument_message_content(item), name=item.agent)
            )
    return messages


def build_main_argument_messages(state: Any, agent: AgentName) -> list[BaseMessage]:
    """主張生成用の system/履歴/指示メッセージ列を組み立てる."""
    template = (
        PromptTemplates.ARGUMENT_SYSTEM_NO_SCHEMA
        if _output_mode(state) == "no_schema"
        else PromptTemplates.ARGUMENT_SYSTEM
    )
    return [
        SystemMessage(content=agent_system(_stance(state, agent), agent, template)),
        *render_history(state.history),
        HumanMessage(content=main_instruction(state)),
    ]


def build_attack_messages(
    state: Any, attacker: AgentName, target: ArgumentRecord, *, purpose: str
) -> list[BaseMessage]:
    """攻撃（defeat/counter）生成用のメッセージ列を組み立てる."""
    template = (
        PromptTemplates.ARGUMENT_SYSTEM_NO_SCHEMA
        if _output_mode(state) == "no_schema"
        else PromptTemplates.ARGUMENT_SYSTEM
    )
    main_argument = getattr(state, "current_argument", None)
    return [
        SystemMessage(content=agent_system(_stance(state, attacker), attacker, template)),
        *render_history(state.history),
        HumanMessage(
            content=attack_instruction(
                purpose, target, state=state, main_argument=main_argument
            )
        ),
    ]


def build_undercut_messages(
    state: Any, attacker: AgentName, target: ArgumentRecord
) -> list[BaseMessage]:
    """Undercut 生成用のメッセージ列を組み立てる."""
    template = (
        PromptTemplates.ARGUMENT_SYSTEM_NO_SCHEMA
        if _output_mode(state) == "no_schema"
        else PromptTemplates.ARGUMENT_SYSTEM
    )
    return [
        SystemMessage(content=agent_system(_stance(state, attacker), attacker, template)),
        *render_history(state.history),
        HumanMessage(content=undercut_instruction(target, state=state)),
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


def _serialize_argument(state: Any, output_argument: ArgumentBody | str) -> str:
    """Argument 出力を ArgumentRecord.argument に格納する文字列へ整形する.

    schema: ArgumentBody から Conc/Ass を導出した JSON。
    no_schema: 自由記述テキストそのまま（前後の空白のみ除去）。
    """
    if _output_mode(state) == "no_schema":
        return cast(str, output_argument).strip()
    return argument_body_json(cast(ArgumentBody, output_argument))


async def generate_main(state: Any, agent: AgentName) -> MainGeneration:
    """Proponent の新しい主張 (A) を生成できるか判定し、可能なら ArgumentRecord 化する."""
    messages = build_main_argument_messages(state, agent)
    schema = (
        MainArgumentAvailabilityOutputFree
        if _output_mode(state) == "no_schema"
        else MainArgumentAvailabilityOutput
    )
    output = cast(
        "MainArgumentAvailabilityOutputFree | MainArgumentAvailabilityOutput",
        await chat_structured(messages, schema),
    )
    if output.can_generate != "YES":
        return MainGeneration(available=False, reason=output.reason, argument=None)
    if output.Argument is None:
        return MainGeneration(available=True, reason=output.reason, argument=None)
    argument = ArgumentRecord(
        type="main",
        argument=_serialize_argument(state, output.Argument),
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
    schema = (
        DefeatingArgumentOutputFree
        if _output_mode(state) == "no_schema"
        else DefeatingArgumentOutput
    )
    output = cast(
        "DefeatingArgumentOutputFree | DefeatingArgumentOutput",
        await chat_structured(messages, schema),
    )
    if output.can_defeat != "YES" or output.Argument is None or output.Attack is None:
        return None
    return ArgumentRecord(
        type="counter" if purpose == "counter" else "defeat",
        argument=_serialize_argument(state, output.Argument),
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
    if _output_mode(state) == "schema" and not target.assumptions:
        return None
    messages = build_undercut_messages(state, attacker, target)
    schema = UndercutOutputFree if _output_mode(state) == "no_schema" else UndercutOutput
    output = cast(
        "UndercutOutputFree | UndercutOutput",
        await chat_structured(messages, schema),
    )
    if output.can_undercut != "YES" or output.Argument is None:
        return None
    return ArgumentRecord(
        type="defeat",
        argument=_serialize_argument(state, output.Argument),
        support=[],
        agent=attacker,
        attack="undercut",
        target_id=target.id,
        target_field="Ass",
        round=getattr(state, "debate_round", 1),
    )


async def generate_generalization(state: Any) -> GeneralizationOutput | GeneralizationOutputFree:
    """両エージェントの warrant を汎化し、再利用可能な基準を導出する."""
    template = (
        PromptTemplates.GENERALIZATION_SYSTEM_NO_SCHEMA
        if _output_mode(state) == "no_schema"
        else PromptTemplates.GENERALIZATION_SYSTEM
    )
    system = synthesis_system("AG1", state.agent1_stance, template)
    user = generalization_instruction(state)
    schema = (
        GeneralizationOutputFree if _output_mode(state) == "no_schema" else GeneralizationOutput
    )
    return await chat_structured(
        [SystemMessage(content=system), HumanMessage(content=user)], schema
    )


async def generate_integration(state: Any) -> IntegrationOutput | IntegrationOutputFree:
    """汎化された基準を一つの統合ルールにまとめる."""
    template = (
        PromptTemplates.INTEGRATION_SYSTEM_NO_SCHEMA
        if _output_mode(state) == "no_schema"
        else PromptTemplates.INTEGRATION_SYSTEM
    )
    system = synthesis_system("AG1", state.agent1_stance, template)
    user = integration_instruction(state)
    schema = IntegrationOutputFree if _output_mode(state) == "no_schema" else IntegrationOutput
    return await chat_structured(
        [SystemMessage(content=system), HumanMessage(content=user)], schema
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
