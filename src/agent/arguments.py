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

from .attack_judge import undercut_relation
from .llm import chat_structured, chat_text
from .prompts import (
    PromptTemplates,
    agent_system,
    attack_instruction,
    integration_instruction,
    main_instruction,
    synthesis_system,
)
from .run_stats import record_discarded, record_regeneration
from .schema.llm_outputs import (
    Antecedent,
    ArgumentBody,
    ArgumentDraft,
    DefeatingArgumentOutput,
    DefeatingArgumentOutputFree,
    IntegrationOutput,
    IntegrationOutputFree,
    MainArgumentAvailabilityOutput,
    MainArgumentAvailabilityOutputFree,
    Rule,
)
from .schema.state import ArgumentRecord, parse_serialized_payload
from .schema.types import AgentName
from .target_selection import field_for, is_schema, quote_in_text, resolve_target


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


def _thread_numbering(state: Any) -> tuple[list[ArgumentRecord], dict[str, int]]:
    """履歴の発言（argument_records）と id→連番の対応を返す。連番は 1 始まりで、履歴の AIMessage と同じ順."""
    records = list(getattr(state, "argument_records", None) or [])
    return records, {record.id: index + 1 for index, record in enumerate(records)}


def numbered_history(state: Any) -> list[BaseMessage]:
    """発言に連番 [n] を付けた履歴を返す（schema / no_schema 共通。本文は変えない）.

    履歴の AIMessage は argument_records と同じ順に 1 対 1 で並ぶ。数が合わないときは番号を付けない。
    """
    messages = render_history(state.history)
    records = list(getattr(state, "argument_records", None) or [])
    if len(messages) != len(records):
        return messages
    return [
        AIMessage(content=f"[{index + 1}] {message.content}", name=message.name)
        for index, message in enumerate(messages)
    ]


def defeat_relations_block(state: Any) -> str:
    """現在のスレッド（今の main 以降）の defeat 関係を、種別を伏せた短い行にして返す.

    schema / no_schema に同じ形で渡す。成立した defeat は「[x] defeats [y]」、判定で成立しなかった
    攻撃は「[x] does not defeat [y]」。互いに defeat しているときは (mutual) を付ける。
    """
    records, number = _thread_numbering(state)
    main = getattr(state, "current_argument", None)
    start = number.get(main.id, 1) if main is not None else 1
    in_thread = {rid for rid, n in number.items() if n >= start}
    won: set[tuple[str, str]] = set()
    failed: set[tuple[str, str]] = set()
    for rel in getattr(state, "defeat_relations", None) or []:
        if rel.attacker_id not in in_thread or rel.target_id not in in_thread:
            continue
        (won if rel.valid else failed).add((rel.attacker_id, rel.target_id))
    lines: list[str] = []
    for attacker, target in sorted(
        won, key=lambda pair: (number[pair[0]], number[pair[1]])
    ):
        mutual = (
            f" (mutual: [{number[target]}] also defeats [{number[attacker]}])"
            if (target, attacker) in won
            else ""
        )
        lines.append(f"[{number[attacker]}] defeats [{number[target]}]{mutual}")
    for attacker, target in sorted(
        failed - won, key=lambda pair: (number[pair[0]], number[pair[1]])
    ):
        lines.append(f"[{number[attacker]}] does not defeat [{number[target]}]")
    body = "\n".join(lines) if lines else "(none yet)"
    return f"<defeat_relations>\n{body}\n</defeat_relations>"


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
    instruction = attack_instruction(
        purpose,
        target,
        state=state,
        main_argument=main_argument,
    )
    _, number = _thread_numbering(state)
    target_label = (
        f"\n<target_number>[{number[target.id]}]</target_number>"
        if target.id in number
        else ""
    )
    return [
        SystemMessage(
            content=agent_system(_stance(state, attacker), attacker, template)
        ),
        *numbered_history(state),
        HumanMessage(
            content=f"{defeat_relations_block(state)}{target_label}\n\n{instruction}"
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
                f'rule {index + 1}\'s consequent ("{consequent}") states a verdict about '
                f'the dialectical game ("{pattern}") instead of a substantive claim about '
                "the issue"
            )
    return None


def resolve_draft(draft: ArgumentDraft) -> tuple[ArgumentBody, list[str]]:
    """LLM が書いた Argument（強い前提は、前の規則の番号）を、保存する形へ直し、形式の違反を返す（空=適合）.

    強い前提の文は、番号が指す前の規則の結論から、コードが入れる（LLM は書き写さない）。
    原著（Prakken & Sartor Def 2.2）の形式条件を、ここで決定的に検査する:
      1. 各規則の強い前提は、それより前の規則の結論に限る（番号は、その規則より前を指す）。
         最初の規則は、強い前提を持たない（前提が空、または weak_negation のみ）。
      2. 同じ結論を持つ規則を、2 つ以上含めない。
      3. 結論は空でなく、defeat の成否そのものを述べる勝敗宣言になっていない。
      4. 非末尾の結論は、後の規則の強い前提として使われる（連結性。最後の規則が論証の warrant）。
    """
    rules = draft.rules or []
    consequents = [(rule.consequent or "").strip() for rule in rules]
    violations: list[str] = []
    resolved: list[Rule] = []
    placeholders = {
        "n/a",
        "none",
        "no additional premise needed",
        "no additional rule needed",
    }
    used: set[int] = set()

    if not rules:
        violations.append("the Argument has no rule")

    for index, (rule, consequent) in enumerate(zip(rules, consequents, strict=True)):
        position = index + 1
        if not consequent:
            violations.append(f"rule {position} has an empty consequent")
        else:
            meta = _meta_conclusion_violation(index, consequent)
            if meta is not None:
                violations.append(meta)
        strong: list[str] = []
        valid_numbers: list[int] = []
        for number in rule.antecedent.from_rules or []:
            if isinstance(number, bool) or not isinstance(number, int) or not 1 <= number < position:
                violations.append(
                    f"rule {position} cites rule {number} as a premise; a premise must be the "
                    "consequent of an EARLIER rule"
                    + (" (the first rule has no premise)" if position == 1 else "")
                )
                continue
            if number not in valid_numbers:
                valid_numbers.append(number)
                strong.append(consequents[number - 1])
                used.add(number)
        weak = [item.strip() for item in rule.antecedent.weak_negation or [] if item.strip()]
        if any(item.lower().rstrip(".") in placeholders for item in weak):
            violations.append(f"rule {position} has a placeholder in weak_negation")
        resolved.append(
            Rule(
                antecedent=Antecedent(
                    strong=strong, from_rules=valid_numbers, weak_negation=weak
                ),
                consequent=consequent,
            )
        )

    seen: set[str] = set()
    for consequent in consequents:
        if consequent and consequent in seen:
            violations.append(f'two rules share the same consequent: "{consequent}"')
        seen.add(consequent)

    for index, consequent in enumerate(consequents[:-1]):
        if consequent and index + 1 not in used:
            violations.append(
                f"non-final consequent of rule {index + 1} is never used by a later rule "
                f'(cite it in from_rules): "{consequent}"'
            )
    return ArgumentBody(rules=resolved), violations


# 形式の違反（番号の誤り、対象の番号の範囲外など）があったとき、書き直させる最大回数。
MAX_REGENERATIONS = 2


def _repair_note(violations: list[str]) -> HumanMessage:
    listed = "\n".join(f"- {item}" for item in violations)
    return HumanMessage(
        content=(
            "<rejected>\nYour previous answer was rejected for the following problems:\n"
            f"{listed}\nAnswer again with the same task, fixing exactly these problems.\n</rejected>"
        )
    )


def _discarded_payload(output: Any) -> dict[str, Any]:
    """却下された出力の、ログに残す内容（理由、Argument、Attack）."""
    payload: dict[str, Any] = {}
    for key in ("can_generate", "can_defeat", "reason", "Argument", "Attack"):
        value = getattr(output, key, None)
        if value is None:
            continue
        payload[key] = value.model_dump(exclude_none=True) if hasattr(value, "model_dump") else value
    return payload


async def _generate_checked(
    messages: list[BaseMessage],
    schema: Any,
    check: Any,
    kind: str,
    context: dict[str, Any] | None = None,
) -> tuple[Any, list[str]]:
    """構造化出力を生成し、check(output) が違反を返したら、最大 MAX_REGENERATIONS 回、書き直させる.

    schema と no_schema のどちらにも、同じ回数を認める（違反が起きた分だけ、呼び出しが増える）。
    書き直しの回数は、run の集計に記録する（kind は main / attack。書き直しても直らなかったときは、
    ``<kind>_gave_up`` に 1 を足す）。却下された下書きは、本文と違反の理由を、context（誰の、どの対象への
    手か）つきで、run の記録に残す。戻り値は、最後の出力と、その違反（空なら適合）。
    """
    output = await chat_structured(messages, schema)
    violations = check(output)
    attempts = 0
    while True:
        if violations:
            record_discarded(
                {
                    "kind": kind,
                    **(context or {}),
                    "attempt": attempts + 1,
                    "gave_up": attempts >= MAX_REGENERATIONS,
                    "violations": list(violations),
                    "output": _discarded_payload(output),
                }
            )
        if not violations or attempts >= MAX_REGENERATIONS:
            break
        attempts += 1
        record_regeneration(kind)
        output = await chat_structured([*messages, _repair_note(violations)], schema)
        violations = check(output)
    if violations:
        record_regeneration(f"{kind}_gave_up")
    return output, violations


def _draft_violations(output: Any) -> list[str]:
    """出力に Argument（schema の下書き）があれば、その形式の違反を返す."""
    draft = getattr(output, "Argument", None)
    if isinstance(draft, ArgumentDraft):
        return resolve_draft(draft)[1]
    return []


async def generate_main(state: Any, agent: AgentName) -> MainGeneration:
    """Proponent の新しい主張 (A) を生成できるか判定し、可能なら ArgumentRecord 化する."""
    messages = build_main_argument_messages(state, agent)
    schema = (
        MainArgumentAvailabilityOutputFree
        if _output_mode(state) == "no_schema"
        else MainArgumentAvailabilityOutput
    )
    output, violations = await _generate_checked(
        messages, schema, _draft_violations, "main", {"agent": agent}
    )
    output = cast(
        "MainArgumentAvailabilityOutputFree | MainArgumentAvailabilityOutput", output
    )
    if output.can_generate != "YES":
        return MainGeneration(available=False, reason=output.reason, argument=None)
    if output.Argument is None:
        return MainGeneration(available=True, reason=output.reason, argument=None)
    if violations:
        return MainGeneration(
            available=False,
            reason="could not produce a well-formed Argument: " + "; ".join(violations),
            argument=None,
        )
    argument = ArgumentRecord(
        type="main",
        argument=_serialize_argument(state, _argument_payload(output.Argument)),
        support=[],
        agent=agent,
        round=state.debate_round,
    )
    return MainGeneration(available=True, reason=None, argument=argument)


def _argument_payload(argument: ArgumentDraft | str) -> ArgumentBody | str:
    """Return the ArgumentBody (schema; strong premises restored) or the free text (no_schema)."""
    if isinstance(argument, ArgumentDraft):
        return resolve_draft(argument)[0]
    return argument


# 直近の generate_attack が「出せない」と答えたときの
# 理由。戻り値は None のままにして既存の呼び出し側を変えないため、タスクごとの ContextVar で渡す。
_decline_reason: ContextVar[str | None] = ContextVar("decline_reason", default=None)


def take_decline_reason() -> str | None:
    """直近の「出せない」理由を取り出して消す（無ければ None）."""
    reason = _decline_reason.get()
    _decline_reason.set(None)
    return reason


def declared_statement(
    state: Any, target: ArgumentRecord, attack: Any
) -> str | None:
    """攻撃側の宣言から、対象の文を得る。実在しなければ None.

    schema は、番号から文を復元する。no_schema は、攻撃側が対象の本文から書き写した文が、
    対象の本文に含まれるかを確かめる。
    """
    method = attack.method
    if is_schema(_output_mode(state)):
        return resolve_target(target, method, attack.target.number)
    statement = str(attack.target.statement).strip()
    return statement if quote_in_text(statement, target.argument) else None


def _attack_violations(state: Any, target: ArgumentRecord) -> Any:
    """攻撃の出力の形式の違反を返す関数を作る（Argument の形式と、対象の指定）."""

    def check(output: Any) -> list[str]:
        if output.can_defeat != "YES" or output.Argument is None or output.Attack is None:
            return []
        violations = _draft_violations(output)
        if declared_statement(state, target, output.Attack) is None:
            if is_schema(_output_mode(state)):
                violations.append(
                    f"Attack.target.number {output.Attack.target.number} is not a number in the "
                    f"list shown for a {output.Attack.method}"
                )
            else:
                violations.append(
                    "Attack.target.statement is not words copied word for word from the target "
                    "argument's text"
                )
        return violations

    return check


async def generate_attack(
    state: Any,
    attacker: AgentName,
    target: ArgumentRecord,
    *,
    purpose: str,
) -> ArgumentRecord | None:
    """攻撃（defeat/counter）主張を LLM 生成し、ArgumentRecord 化する.

    攻撃の対象は、schema は、対象の論証から見せた番号つきの一覧から、番号で選ばせ、文はコードが復元する。
    no_schema は、対象の本文から書き写した文を出させ、本文に含まれるかを照合する。
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
    output, violations = await _generate_checked(
        messages,
        schema,
        _attack_violations(state, target),
        "attack",
        {"agent": attacker, "target_id": target.id, "purpose": purpose},
    )
    output = cast("DefeatingArgumentOutputFree | DefeatingArgumentOutput", output)
    if output.can_defeat != "YES" or output.Argument is None or output.Attack is None:
        _decline_reason.set(output.reason or "(no reason given)")
        return None
    if violations:
        _decline_reason.set(
            "could not produce a well-formed attack: " + "; ".join(violations)
        )
        return None
    # 非反復の自己点検（反撃だけ）。自分で「新しい理由を足さない」と申告したら、その反撃は
    # 出さない（P は同じ内容の手を、2度指せない）。反論側は、論文でも繰り返してよいので対象外。
    novelty = output.Novelty if purpose == "counter" else None
    if novelty is not None and (
        novelty.adds_new_reason != "YES" or not novelty.new_reason.strip()
    ):
        _decline_reason.set(
            "Repeats a reason I already used"
            + (
                f" (closest earlier argument: {novelty.closest_earlier_id})"
                if novelty.closest_earlier_id
                else ""
            )
            + "; there is no new reason to add."
        )
        return None
    _decline_reason.set(None)
    novelty_note = (
        f"[closest earlier: {novelty.closest_earlier_id}] {novelty.new_reason.strip()}"
        if novelty is not None
        else None
    )
    method = output.Attack.method
    statement = declared_statement(state, target, output.Attack)
    return ArgumentRecord(
        type="counter" if purpose == "counter" else "defeat",
        argument=_serialize_argument(state, _argument_payload(output.Argument)),
        support=[],
        agent=attacker,
        attack=method,
        target_id=target.id,
        target_field=field_for(method),  # type: ignore[arg-type]
        target_statement=statement,
        round=getattr(state, "debate_round", 1),
        novelty_note=novelty_note,
    )


async def ask_existing_undercut(
    state: Any,
    author: AgentName,
    own: ArgumentRecord,
    attack: ArgumentRecord,
) -> str | None:
    """すでにある論証 own が、相手の rebut（attack）を undercut しているかを、別の LLM に判定させる.

    新しい論証は作らない（Prakken & Sartor の defeat は、すでにある2論証の組の関係）。
    戻り値は undercut している場合の理由、していなければ None。
    undercut は、attack の仮定（Ass）の否定を、own の結論が確立していることなので、attack の
    仮定の一覧を判定者に渡す。schema は attack の Ass、no_schema は attack の本文に明示された
    例外条項（引用）。仮定がなければ undercut しようがないので、LLM を呼ばずに None。
    `author` は、判定の呼び出し側の互換のために残す（判定者は、書き手とは別のモデル）。
    """
    verdict = await undercut_relation(
        state, own, attack, context="rebut_defeat_condition"
    )
    if not verdict.holds:
        return None
    return verdict.reason or "(no reason given)"


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
            f"\nShared integrated rules produced in earlier rounds:\n{rules_text}\n"
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
