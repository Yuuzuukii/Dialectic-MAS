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
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, cast

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from .argumentation_model import AttackMatch
from .llm import chat_structured, chat_text
from .prompts import (
    PromptTemplates,
    agent_system,
    attack_extends_instruction,
    attack_instruction,
    existing_undercut_instruction,
    integration_instruction,
    main_instruction,
    synthesis_system,
)
from .schema.llm_outputs import (
    ArgumentBody,
    AttackExtendsOutput,
    DefeatingArgumentOutput,
    DefeatingArgumentOutputFree,
    ExistingUndercutOutput,
    IntegrationOutput,
    IntegrationOutputFree,
    MainArgumentAvailabilityOutput,
    MainArgumentAvailabilityOutputFree,
)
from .schema.state import ArgumentRecord, parse_serialized_payload
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

    state.history には、発話の AIMessage と、その発話を引き出した指示の HumanMessage が
    交互に入っている。ここでは指示を除いて発話だけを返す（指示は手番ごとに最後に1つだけ付ける）。
    新設計では state.history は BaseMessage のリスト。古いテストや移行中の呼び出しで
    ArgumentRecord が渡された場合だけ、Argument 本体のみの AIMessage として互換変換する。
    """
    messages: list[BaseMessage] = []
    for item in history:
        if isinstance(item, HumanMessage):
            # 過去の手番に出した指示（主張を作れ・can_generate=NO など）は、その手番の
            # エージェント宛てのもの。履歴に残すと、別の手番で自分宛ての指示と取り違えたり、
            # 反論側が proponent 用の非反復の制約を引き継いだりするため、発話だけを残す。
            continue
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
            )
        ),
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


# Argument の consequent が「勝敗の確定・対話ゲームの状態」を述べているだけで、
# トピックについての実質的な主張になっていない場合に検出する語彙。誤検出があれば
# ここを調整する（docs/argumentation_model_rebuild_plan.md §9 要確認事項 #5）。
_META_CONCLUSION_PATTERNS = (
    "fails to defeat",
    "does not defeat",
    "fail to defeat",
    "fails to undercut",
    "does not undercut",
    "fails to rebut",
    "does not rebut",
    "does not follow from its premises",
    "does not follow from the premises",
    "the target attack",
    "the target argument",
    "is not defeated",
    "is defeated",
)


def _meta_conclusion_violation(index: int, consequent: str) -> str | None:
    """Consequent が defeat 判定そのものを述べる勝敗宣言になっていないか検査する."""
    lowered = consequent.lower()
    for pattern in _META_CONCLUSION_PATTERNS:
        if pattern in lowered:
            return (
                f"rule {index + 1}'s consequent (\"{consequent}\") states a verdict about "
                f'the dialectical game ("{pattern}") instead of a substantive claim about '
                "the issue"
            )
    return None


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
      5. consequentが「defeatの成否」自体を述べる勝敗宣言になっていない
         （実質的な主張ではなく対話ゲームの状態を書いてしまう問題への対処。
         docs/argumentation_model_rebuild_plan.md §4.7 参照）。
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
        else:
            meta_violation = _meta_conclusion_violation(index, consequent)
            if meta_violation is not None:
                violations.append(meta_violation)
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


async def _generate_structured_argument(
    messages: list[BaseMessage], schema: Any
) -> Any:
    """構造化出力で Argument を1回だけ生成して返す.

    形式の検証（`validate_argument_body`）に違反しても、再生成（修復）は行わない。
    修復は schema にだけ追加の LLM 呼び出しを与え、no_schema との比較を不公平にするうえ、
    修復の応答が本来の判断（反論の可否など）を歪めうるため。違反は診断用に
    `validate_argument_body` で事後に数えられる。
    """
    return await chat_structured(messages, schema)


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


# 直近の generate_attack / ask_attack_extends が「出せない」と答えたときの
# 理由。戻り値は None のままにして既存の呼び出し側を変えないため、タスクごとの ContextVar で渡す。
_decline_reason: ContextVar[str | None] = ContextVar("decline_reason", default=None)


def take_decline_reason() -> str | None:
    """直近の「出せない」理由を取り出して消す（無ければ None）."""
    reason = _decline_reason.get()
    _decline_reason.set(None)
    return reason


async def generate_attack(
    state: Any,
    attacker: AgentName,
    target: ArgumentRecord,
    *,
    purpose: str,
) -> ArgumentRecord | None:
    """攻撃（defeat/counter）主張を LLM 生成し、ArgumentRecord 化する.

    非反復（同じ target への実質的に同じ内容の繰り返しを避ける）は counter 側
    （proponent）の attack_instruction の指示文だけで扱う。Prakken & Sartor の
    dialogue game（Definition 4.5 条件2）では非反復は proponent の手だけに課される
    制約であり、opponent（defeat 側）には対応する制約がない（同定義の Example 4.4
    は opponent に非反復を課すと正当化判定が理論より緩くなることを示す）。
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
        _decline_reason.set(output.reason or "(no reason given)")
        return None
    # 非反復の自己点検（反撃だけ）。自分で「新しい理由を足さない」と申告したら、その反撃は
    # 出さない（P は同じ内容の手を、2度指せない）。反論側は、論文でも繰り返してよいので対象外。
    novelty = output.Novelty if purpose == "counter" else None
    if novelty is not None and (
        novelty.adds_new_reason != "YES" or not novelty.new_reason.strip()
    ):
        _decline_reason.set(
            "Repeats a reason I already used"
            + (f" (closest earlier argument: {novelty.closest_earlier_id})" if novelty.closest_earlier_id else "")
            + "; there is no new reason to add."
        )
        return None
    _decline_reason.set(None)
    novelty_note = (
        f"[closest earlier: {novelty.closest_earlier_id}] {novelty.new_reason.strip()}"
        if novelty is not None
        else None
    )
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
        novelty_note=novelty_note,
    )


async def ask_existing_undercut(
    state: Any,
    author: AgentName,
    own: ArgumentRecord,
    attack: ArgumentRecord,
) -> str | None:
    """すでにある論証 own が、相手の rebut（attack）を undercut しているかを author に問う.

    新しい論証は作らない（Prakken & Sartor の defeat は、すでにある2論証の組の関係）。
    戻り値は undercut している場合の理由、していなければ None。
    undercut は、相手が仮定（Ass）として明示した文を否定することなので、仮定が宣言されて
    いなければ undercut しようがない。schema では、attack に仮定（weak_negation）が無ければ
    LLM を呼ばずに None。no_schema は、論証の本文が自由記述で仮定を宣言する構造を持たない
    ので、常に None（schema の構造が可能にする判定を、no_schema に持ち込まない。
    仮定の有無を LLM に判断させると、作者が「自分の論証が undercut している」と答えやすく、
    実測で O の rebut の93%が取り消された）。
    """
    if _output_mode(state) != "schema":
        return None
    assumptions = attack.assumptions
    if not assumptions:
        return None
    system = agent_system(
        _stance(state, author), author, PromptTemplates.ATTACK_EXTENDS_SYSTEM
    )
    messages = [
        SystemMessage(content=system),
        *render_history(state.history),
        HumanMessage(
            content=existing_undercut_instruction(
                own, attack, assumptions=assumptions, state=state
            )
        ),
    ]
    output = await chat_structured(messages, ExistingUndercutOutput)
    if output.undercuts != "YES":
        return None
    return output.reason or "(no reason given)"


async def ask_attack_extends(
    state: Any,
    attacker: AgentName,
    b_argument: ArgumentRecord,
    c_argument: ArgumentRecord,
) -> AttackMatch | None:
    """B（attackerが既に行った攻撃）が、相手の新しいカウンターCにも及ぶかを問い、及ぶ場合はBからCへの攻撃関係（method・対象）を改めて宣言させる.

    B の作者である attacker 自身に尋ねる（新しい論証は生成しない）。attack/defeat は
    論証単体の性質ではなく「特定の2論証の組」に対して定義される関係（Prakken &
    Sartor）なので、B が元の対象に対して宣言した `.attack`/`target_statement` を
    そのまま C に流用してはならない。戻り値はこの B-C 間で改めて判定された
    攻撃関係（Noneなら及ばない、または C に対して有効な攻撃が成立しない）。
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
    if output.attack_extends != "YES" or output.Attack is None:
        _decline_reason.set(output.reason or "(no reason given)")
        return None
    _decline_reason.set(None)
    return AttackMatch(
        method=output.Attack.method,
        field=output.Attack.target.field,
        statement=output.Attack.target.statement,
    )


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


def _dialogue_history_json(state: Any) -> str:
    """最終回答向けに dialogue_history を JSON テキスト化する.

    各レコードの "argument" は schema 条件では既に JSON 文字列として格納されている
    （ArgumentRecord.argument）。これをそのまま外側の dict と一緒に json.dumps すると、
    内側の JSON 文字列がエスケープされた1行の文字列になり（二重エンコード）、
    読み手のモデルにとって rules/Conc/Ass の構造がひどく読みにくくなる。ここで
    "argument" を一旦パースしてからネストした JSON オブジェクトとして埋め込み直す
    （パースできない場合は no_schema の自由記述とみなしそのまま文字列で残す）。
    """
    history = []
    for record in state.dialogue_history:
        record = dict(record)
        argument = record.get("argument")
        if isinstance(argument, str):
            parsed = parse_serialized_payload(argument)
            if parsed:
                record["argument"] = parsed
        history.append(record)
    return json.dumps(history, ensure_ascii=False, indent=2)


async def generate_final_answer(state: Any) -> str:
    """対話履歴を踏まえて自然文回答を生成する.

    通常は justified な主張から作る。合意に至らず暫定回答を作る場合
    (consensus_reached is False) は、合意なしであることを明示する専用プロンプトを使う。
    justified された側が AG1/AG2 のどちらであっても、AG1 が中立な統合役として
    客観的に書く（generalize/integrate と同じ「AG1=synthesis operator」の役割分担）。
    """
    justified = state.justified_argument
    dialogue_history = _dialogue_history_json(state)
    is_schema = _output_mode(state) != "no_schema"
    if state.integrated_rules:
        rules_text = "\n".join(f"- {rule}" for rule in state.integrated_rules)
        integrated_rules_block = (
            "\nShared integrated rules produced in earlier rounds:\n"
            f"{rules_text}\n"
        )
    else:
        integrated_rules_block = ""

    if state.consensus_reached is False:
        system = (
            PromptTemplates.FINAL_ANSWER_NO_CONSENSUS_SYSTEM
            if is_schema
            else PromptTemplates.FINAL_ANSWER_NO_CONSENSUS_SYSTEM_NO_SCHEMA
        )
        user = PromptTemplates.FINAL_ANSWER_NO_CONSENSUS_USER.format(
            question=state.question,
            agent1_stance=state.agent1_stance,
            agent2_stance=state.agent2_stance,
            integrated_rules_block=integrated_rules_block,
            dialogue_history=dialogue_history,
            justified_argument=justified,
        ).strip()
    else:
        system = (
            PromptTemplates.FINAL_ANSWER_SYSTEM
            if is_schema
            else PromptTemplates.FINAL_ANSWER_SYSTEM_NO_SCHEMA
        )
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
