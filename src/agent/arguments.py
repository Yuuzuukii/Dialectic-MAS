"""LLM 生成呼び出しの単一集約点.

各手番（main / attack[defeat,counter] / undercut）と合成（integrate: 汎化+統合を1ステップで行う）、
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
    attack_extends_instruction,
    attack_instruction,
    integration_instruction,
    main_instruction,
    synthesis_system,
    target_engagement_instruction,
    undercut_instruction,
)
from .schema.llm_outputs import (
    ArgumentBody,
    AttackExtendsOutput,
    DefeatingArgumentOutput,
    DefeatingArgumentOutputFree,
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
    """LLM 履歴の AIMessage に入れる内容を返す.

    schema: id/round/phase/agent/status/attack/target_id/target_statement を含む envelope +
    Argument 本体（_HISTORY_FORMAT が説明する形）。従来は Argument 本体（rules/Conc/Ass）
    だけを渡しており、どのターンが誰の何を攻撃したものかという attack メタデータが
    ArgumentRecord には保持されているのに履歴からは完全に欠落していた（実装バグ）。
    no_schema: 自由記述テキストそのまま（従来通り）。
    """
    body = record.body
    if not body:
        return record.argument
    envelope: dict[str, Any] = {
        "id": record.id,
        "round": record.round,
        "phase": record.type,
        "agent": record.agent,
    }
    if record.status is not None:
        envelope["status"] = record.status
    if record.attack is not None:
        envelope["attack"] = record.attack
        envelope["target_id"] = record.target_id
        envelope["target_statement"] = record.target_statement
    envelope["Argument"] = body
    return json.dumps(envelope, ensure_ascii=False, indent=2)


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


async def _target_engagement_point(
    state: Any, attacker: AgentName, target: ArgumentRecord, template: str
) -> str:
    """本体の Argument を組み立てる前に、狙う弱点を一言で言語化させる（schema条件専用）.

    Attack.target と Argument.rules を1回の生成で同時に埋めさせると、両者が独立に
    生成されて反論の中身が対象の具体的な内容に触れないまま一般論で済まされることが
    実測で確認された。ここで軽量な自由記述の一段階を先に挟み、その結果を本体生成の
    指示（attack_instruction の target_engagement_point）に埋め込むことで、対象への
    言及を本体の推論の前提条件にする。
    """
    messages = [
        SystemMessage(
            content=agent_system(_stance(state, attacker), attacker, template)
        ),
        HumanMessage(content=target_engagement_instruction(target)),
    ]
    text = await chat_text(messages)
    return text.strip()


async def build_attack_messages(
    state: Any, attacker: AgentName, target: ArgumentRecord, *, purpose: str
) -> list[BaseMessage]:
    """攻撃（defeat/counter）生成用のメッセージ列を組み立てる."""
    template = (
        PromptTemplates.ARGUMENT_SYSTEM_NO_SCHEMA
        if _output_mode(state) == "no_schema"
        else PromptTemplates.ARGUMENT_SYSTEM
    )
    main_argument = getattr(state, "current_argument", None)
    engagement_point = (
        await _target_engagement_point(state, attacker, target, template)
        if _output_mode(state) != "no_schema"
        else None
    )
    return [
        SystemMessage(
            content=agent_system(_stance(state, attacker), attacker, template)
        ),
        *render_history(state.history),
        HumanMessage(
            content=attack_instruction(
                purpose,
                target,
                state=state,
                main_argument=main_argument,
                engagement_point=engagement_point,
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
        SystemMessage(
            content=agent_system(_stance(state, attacker), attacker, template)
        ),
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


def validate_argument_body(body: ArgumentBody) -> list[str]:
    """各 rule の形式的不変条件を機械的に検証し、違反メッセージのリストを返す（空=適合）.

    以前は _SCHEMA_OVERLAY と ArgumentBody.rules の description に散文で二重に書いていた
    連鎖制約を、生成プロンプトから外してここで決定論的に検証する（GPT-5 の推論予算を
    帳簿付けに費やさせないため）。

    ここで強制する形式条件:
      1. 各ruleのconsequentは空でない。
      2. 各ruleは意味のあるstrongまたはweak_negationを少なくとも1つ持つ。
      3. 2つ以上のruleが同じconsequentを持たない（重複禁止）。
      4. 非末尾consequentは、後続ruleのstrong先行詞として再利用される（連結性）。
    旧仕様の「r_i (i>1) の strong 先行詞はすべて先行 consequent でなければならない」は、
    後段で新しい前提事実を導入する妥当な論証まで弾くため、あえて強制しない。
    """
    rules = body.rules or []
    consequents = [(rule.consequent or "").strip() for rule in rules]
    violations: list[str] = []
    placeholder_antecedents = {
        "n/a",
        "no additional premise needed",
        "no additional rule needed",
        "none",
    }

    for index, (rule, consequent) in enumerate(zip(rules, consequents, strict=True)):
        if not consequent:
            violations.append(f"rule {index + 1} has an empty consequent")
        antecedents = [
            *(rule.antecedent.strong or []),
            *(rule.antecedent.weak_negation or []),
        ]
        meaningful = [
            item.strip()
            for item in antecedents
            if item.strip().lower().rstrip(".") not in placeholder_antecedents
        ]
        if not meaningful:
            violations.append(
                f"rule {index + 1} has no meaningful strong or weak_negation antecedent"
            )

    seen: set[str] = set()
    for consequent in consequents:
        if consequent and consequent in seen:
            violations.append(f'two rules share the same consequent: "{consequent}"')
        seen.add(consequent)

    used_as_strong: set[str] = set()
    for rule in rules:
        for strong in rule.antecedent.strong or []:
            stripped = (strong or "").strip()
            if stripped:
                used_as_strong.add(stripped)
    for index, consequent in enumerate(consequents[:-1]):
        if consequent and consequent not in used_as_strong:
            violations.append(
                f"non-final consequent of rule {index + 1} is never used by a "
                f'later rule: "{consequent}"'
            )
    return violations


def _repair_instruction(violations: list[str]) -> str:
    """検証で見つかった連鎖違反を、再生成時に添える矯正指示へ整形する."""
    bullet = "\n".join(f"- {violation}" for violation in violations)
    return (
        "<repair>\n"
        "Your previous Argument violated the rule-structure contract:\n"
        f"{bullet}\n"
        "Regenerate the Argument so every rule has a non-empty consequent and at least "
        "one meaningful strong or weak_negation antecedent, every non-final consequent "
        "is reused as a strong antecedent of a later rule, and no two rules share the "
        "same consequent. Never add placeholder rules such as 'No additional rule "
        "needed.' Keep the substance of your reasoning; only fix the structure.\n"
        "</repair>"
    )


async def _generate_structured_argument(
    messages: list[BaseMessage], schema: Any
) -> Any:
    """構造化 Argument を生成し、形式的不変条件に違反した場合のみ1回だけ再生成する.

    schema 系のみ矯正メッセージを添えて再生成する。
    no_schema（Argument が自由記述文字列）や Argument を含まない出力はそのまま返す。
    再生成後は結果の可否によらずそのまま採用し、無限ループや hard fail は避ける。
    """
    output = await chat_structured(messages, schema)
    body = getattr(output, "Argument", None)
    if isinstance(body, ArgumentBody):
        violations = validate_argument_body(body)
        if violations:
            output = await chat_structured(
                [*messages, HumanMessage(content=_repair_instruction(violations))],
                schema,
            )
    return output


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
        await _generate_structured_argument(messages, schema),
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
    """攻撃（defeat/counter）主張を LLM 生成し、ArgumentRecord 化する.

    purpose="defeat" のリトライ（o_defeat_a が同一 target に対して別候補 B' を試す2回目
    以降）では、生成された攻撃自身に has_new_point（このスレッド内の既存の試みと比べて
    実質的に新しい角度か）を自己申告させる。生成の指示（attack_instruction）は変更せず、
    通常どおり生成させた上で事後的に判定するだけなので、生成内容そのものを歪めない
    （過去に試した「別の対象を攻撃しろ」「内容を変えろ」という生成時介入とは異なる）。
    False なら can_defeat=NO と同様に None を返し、新しい攻撃が尽きたとみなして
    スレッドを終える（mad/free_debate の has_new_point 早期停止と同じ発想）。
    """
    messages = await build_attack_messages(state, attacker, target, purpose=purpose)
    schema = (
        DefeatingArgumentOutputFree
        if _output_mode(state) == "no_schema"
        else DefeatingArgumentOutput
    )
    output = cast(
        "DefeatingArgumentOutputFree | DefeatingArgumentOutput",
        await _generate_structured_argument(messages, schema),
    )
    if output.can_defeat != "YES" or output.Argument is None or output.Attack is None:
        return None
    if (
        purpose == "defeat"
        and getattr(state, "attack_attempt_count", 0) > 0
        and not output.has_new_point
    ):
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
    schema = (
        UndercutOutputFree if _output_mode(state) == "no_schema" else UndercutOutput
    )
    output = cast(
        "UndercutOutputFree | UndercutOutput",
        await _generate_structured_argument(messages, schema),
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


async def ask_attack_extends(
    state: Any,
    attacker: AgentName,
    b_argument: ArgumentRecord,
    c_argument: ArgumentRecord,
) -> bool:
    """B（attackerが既に行った攻撃）が、相手の新しいカウンターCにも及ぶかを問う.

    B の作者である attacker 自身に YES/NO で尋ねる（新しい論証は生成しない）.
    """
    system = agent_system(
        _stance(state, attacker), attacker, PromptTemplates.ATTACK_EXTENDS_SYSTEM
    )
    messages = [
        SystemMessage(content=system),
        *render_history(state.history),
        HumanMessage(
            content=attack_extends_instruction(b_argument, c_argument, state=state)
        ),
    ]
    output = await chat_structured(messages, AttackExtendsOutput)
    return output.attack_extends == "YES"


async def generate_integration(state: Any) -> IntegrationOutput | IntegrationOutputFree:
    """両エージェントの warrant を汎化した上で、一つの統合ルールにまとめる（1ステップ）."""
    template = (
        PromptTemplates.INTEGRATION_SYSTEM_NO_SCHEMA
        if _output_mode(state) == "no_schema"
        else PromptTemplates.INTEGRATION_SYSTEM
    )
    system = synthesis_system("AG1", state.agent1_stance, template)
    user = integration_instruction(state)
    schema = (
        IntegrationOutputFree
        if _output_mode(state) == "no_schema"
        else IntegrationOutput
    )
    return await chat_structured(
        [SystemMessage(content=system), HumanMessage(content=user)], schema
    )


async def generate_final_answer(state: Any) -> str:
    """対話履歴を踏まえて自然文回答を生成する.

    通常は justified な主張から作る。合意に至らず暫定回答を作る場合
    (consensus_reached is False) は、合意なしであることを明示する専用プロンプトを使う。
    justified された側が AG1/AG2 のどちらであっても、AG1 が中立な統合役として
    客観的に書く（generalize/integrate と同じ「AG1=synthesis operator」の役割分担）。
    """
    justified = state.justified_argument
    dialogue_history = json.dumps(state.dialogue_history, ensure_ascii=False, indent=2)
    if state.integrated_rules:
        rules_text = "\n".join(f"- {rule}" for rule in state.integrated_rules)
        integrated_rules_block = (
            "\nShared integrated rules produced in earlier rounds:\n"
            f"{rules_text}\n"
        )
    else:
        integrated_rules_block = ""

    if state.consensus_reached is False:
        system = PromptTemplates.FINAL_ANSWER_NO_CONSENSUS_SYSTEM
        user = PromptTemplates.FINAL_ANSWER_NO_CONSENSUS_USER.format(
            question=state.question,
            agent1_stance=state.agent1_stance,
            agent2_stance=state.agent2_stance,
            integrated_rules_block=integrated_rules_block,
            dialogue_history=dialogue_history,
            justified_argument=justified,
        ).strip()
    else:
        system = PromptTemplates.FINAL_ANSWER_SYSTEM
        user = PromptTemplates.FINAL_ANSWER_USER.format(
            question=state.question,
            agent1_stance=state.agent1_stance,
            agent2_stance=state.agent2_stance,
            integrated_rules_block=integrated_rules_block,
            dialogue_history=dialogue_history,
            justified_argument=justified,
        ).strip()

    # 最終回答は constraint_preservation（両スタンスの要件を取り込めているか）で
    # 採点される。簡潔すぎると両者の制約を名指しできず不利になるため verbosity を上げる。
    return await chat_text(
        [SystemMessage(content=system), HumanMessage(content=user)],
        model=os.getenv("MODEL", "gpt-5.4-mini"),
        verbosity="high",
    )
