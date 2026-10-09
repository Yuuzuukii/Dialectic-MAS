"""攻撃（rebut / undercut）の成立を、議論を書く側とは別の LLM に判定させる.

議論を書く側の LLM は、攻撃の種類と対象（番号）を宣言するだけで、宣言が成り立つかは、ここで、
別のモデル（既定 gpt-5.4-mini）が判定する。判定者には、問い、対象、攻撃の本文だけを、手法に依らない
形（規則列は文章にして）で渡す。スタンス、手法名、決着状態は見せない。

定義は Prakken & Sartor (1997) による（結論は、全規則の結論。途中の結論でもよい）:

- rebut: 攻撃の結論のどれかが、対象の宣言された結論 S の否定（S の主張を否定し、両方を問いへの答えとして維持できない）である。程度やヘッジの違い（「確実には…ない」と「…する」）だけでは、rebut を妨げない。
- undercut: 攻撃の結論のどれかが、対象の仮定の否定である（その仮定の X が成り立つことを、攻撃自身の推論が確立する）。
- すでにある論証による undercut（rebut の defeat の第 3 条件）は、undercut と同じ判定を、役割を入れ替えて行う。
  対象の仮定は宣言されていないので、対象の仮定の一覧を渡し、どれかが否定されているかを聞く。
  schema では対象の Ass を、no_schema では本文に明示された例外条項（引用）を、一覧にする。

環境変数: JUDGE_MODEL（既定 gpt-5.4-mini）、JUDGE_REASONING_EFFORT（既定 medium）。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from langchain_core.callbacks import get_usage_metadata_callback
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from .dialogue_transcript import render_argument_text
from .llm import chat_structured
from .run_stats import record_judge, record_judgement
from .schema.state import ArgumentRecord
from .target_selection import is_schema

_DEFAULT_JUDGE_MODEL = "gpt-5.4-mini"
_DEFAULT_JUDGE_EFFORT = "medium"

# no_schema の仮定は、論証の本文から取り出す。同じ論証への判定で何度も取り出さないよう、id で覚える。
_presumption_cache: dict[str, list[str]] = {}


class RebutJudgement(BaseModel):
    """rebut の成立の判定."""

    attack_conclusion_quote: str = Field(
        description="The conclusion of the attack that comes closest to opposing the target statement, quoted word for word."
    )
    rebuts: bool = Field(
        description="True only if that conclusion directly opposes the target statement: it denies what the target statement asserts."
    )
    reason: str = Field(description="One sentence explaining the judgement.")


class UndercutJudgement(BaseModel):
    """undercut の成立の判定."""

    undercut_assumption_number: int | None = Field(
        default=None,
        description="The number of ONE listed assumption that the attack undercuts, or null if it undercuts none.",
    )
    attack_conclusion_quote: str = Field(
        default="",
        description="The conclusion of the attack that contradicts that assumption, quoted word for word (empty if none).",
    )
    reason: str = Field(description="One sentence explaining the judgement.")


class PresumptionList(BaseModel):
    """論証の本文に、明示された例外条項（既定として頼る前提）の一覧."""

    presumptions: list[str] = Field(
        default_factory=list,
        description="Presumptions the argument states explicitly, each quoted verbatim from the argument; empty if none.",
    )


@dataclass(frozen=True)
class RebutVerdict:
    """rebut の判定結果."""

    holds: bool
    reason: str
    quote: str = ""


@dataclass(frozen=True)
class UndercutVerdict:
    """undercut の判定結果（成立するなら、否定された仮定）."""

    holds: bool
    assumption: str | None
    reason: str
    quote: str = ""


_REBUT_PROMPT = """<task>
You are an independent judge of an argumentation dialogue. Decide whether the ATTACK rebuts the TARGET STATEMENT.
</task>

<definition>
The attack rebuts the target statement S when one of the attack's conclusions directly opposes S: it denies what S asserts, so the two cannot both be maintained as the answer to the issue.
Any conclusion of the attack counts, including an intermediate one; it need not be the attack's final conclusion.
A difference of degree or hedging does not prevent a rebut: for example, "X does not reliably happen" opposes "X happens" when it denies what S asserts.
It does NOT count when the attack only supports a different option, narrows the scope of S, questions whether S matters, argues that S is not needed, addresses a different claim than S, or merely disagrees in tone.
Judge the meaning, not the wording or the format: a prose argument and a chain of rules are treated alike.
</definition>

<issue>
{issue}
</issue>

<target_statement>
{statement}
</target_statement>

<attack>
{attack}
</attack>

<procedure>
1. Quote, word for word, the conclusion of the attack that comes closest to opposing the target statement.
2. Decide whether that conclusion directly opposes the target statement, that is, whether it denies what the target statement asserts.
</procedure>"""

_UNDERCUT_PROMPT = """<task>
You are an independent judge of an argumentation dialogue. Decide whether the ATTACK undercuts the TARGET by denying one of the listed ASSUMPTIONS of the target.
</task>

<definition>
An assumption is an exception clause that the target's reasoning takes to hold by default ("X is not the case" / "there is no evidence that X").
The attack undercuts an assumption when the attack's own reasoning establishes that X does hold: one of the attack's conclusions is the contradictory of the assumption.
Any conclusion of the attack counts, including an intermediate one.
It does NOT count when the attack only asserts the opposite of the target's final conclusion, says the target's framing is inappropriate, or states something related to X without establishing X.
Judge only what the attack already says; do not add reasoning that the attack does not contain.
Judge the meaning, not the wording or the format: a prose argument and a chain of rules are treated alike.
{presumption_rule}</definition>

<issue>
{issue}
</issue>

<target>
{target}
</target>

<assumptions>
{assumptions}
</assumptions>

<attack>
{attack}
</attack>

<procedure>
For each assumption in turn: quote the conclusion of the attack that contradicts it, if there is one, and decide whether the attack's reasoning establishes it.
Then report the number of ONE assumption that the attack undercuts, or null if it undercuts none.
</procedure>"""

_PRESUMPTION_RULE = """Each listed item must be a presumption that the target's reasoning relies on by default (an exception it takes to be absent), not the target's conclusion and not a plain fact it states. An item that is not such a presumption cannot be undercut: do not select it.
"""

_EXTRACT_PROMPT = """<task>
List the presumptions that the argument states explicitly: exception clauses that it takes to hold by default.
</task>

<rules>
- Only phrases that the argument itself marks as a presumption ("unless", "as long as", "provided that", "assuming there is no", "absent evidence", "no evidence that"). Quote each one verbatim from the argument.
- Do not infer presumptions that the argument does not state. Do not list its premises or its conclusions.
- Return an empty list if the argument states none.
</rules>

<argument>
{argument}
</argument>"""


def _mode(state: Any) -> str:
    return str(getattr(state, "output_mode", "schema"))


def _issue(state: Any) -> str:
    return str(getattr(state, "question", "") or "")


def judge_model() -> str:
    """判定に使うモデル名（議論を書く側とは別のモデル）."""
    return os.getenv("JUDGE_MODEL") or _DEFAULT_JUDGE_MODEL


def _judge_effort() -> str:
    return os.getenv("JUDGE_REASONING_EFFORT") or _DEFAULT_JUDGE_EFFORT


def _numbered(items: list[str]) -> str:
    return "\n".join(f"[{index}] {item}" for index, item in enumerate(items, start=1))


def argument_block(record: ArgumentRecord, mode: str) -> str:
    """判定者に渡す論証の見せ方。schema は、規則を文章にした本文に、結論の一覧を添える."""
    text = render_argument_text(record.argument)
    if not is_schema(mode):
        return text
    conclusions = record.conclusions
    if not conclusions:
        return text
    return f"Conclusions:\n{_numbered(conclusions)}\n\nFull argument:\n{text}"


def rebut_prompt(state: Any, attack: ArgumentRecord, statement: str) -> str:
    """Rebut の判定プロンプトを組む."""
    return _REBUT_PROMPT.format(
        issue=_issue(state),
        statement=statement,
        attack=argument_block(attack, _mode(state)),
    )


def undercut_prompt(
    state: Any,
    attack: ArgumentRecord,
    target: ArgumentRecord,
    assumptions: list[str],
    *,
    presumption_check: bool,
) -> str:
    """Undercut の判定プロンプトを組む（assumptions は、対象の仮定の一覧）."""
    mode = _mode(state)
    return _UNDERCUT_PROMPT.format(
        issue=_issue(state),
        target=argument_block(target, mode),
        assumptions=_numbered(assumptions),
        attack=argument_block(attack, mode),
        presumption_rule=_PRESUMPTION_RULE if presumption_check else "",
    )


def extract_prompt(argument: ArgumentRecord) -> str:
    """no_schema の論証から、明示された例外条項を取り出すプロンプトを組む."""
    return _EXTRACT_PROMPT.format(argument=argument.argument.strip())


async def _ask(prompt: str, schema: type[BaseModel], kind: str) -> Any:
    """判定者に 1 回聞く。呼び出しの回数とトークン数を、run の集計に記録する."""
    with get_usage_metadata_callback() as usage:
        output = await chat_structured(
            [HumanMessage(content=prompt)],
            schema,
            model=judge_model(),
            reasoning_effort=_judge_effort(),
        )
    record_judge(kind, usage.usage_metadata)
    return output


async def judge_rebut(
    state: Any,
    attack: ArgumentRecord,
    statement: str,
    target: ArgumentRecord | None = None,
) -> RebutVerdict:
    """攻撃の結論のどれかが、対象の結論 S の否定になっているかを判定する（理由は、run の記録に残す）."""
    out: RebutJudgement = await _ask(
        rebut_prompt(state, attack, statement), RebutJudgement, "rebut"
    )
    record_judgement(
        {
            "kind": "rebut",
            "attack_id": attack.id,
            "target_id": target.id if target is not None else None,
            "target_statement": statement,
            "holds": bool(out.rebuts),
            "attack_conclusion_quote": out.attack_conclusion_quote,
            "reason": out.reason,
        }
    )
    return RebutVerdict(bool(out.rebuts), out.reason, out.attack_conclusion_quote)


async def judge_undercut(
    state: Any,
    attack: ArgumentRecord,
    target: ArgumentRecord,
    assumptions: list[str],
    *,
    presumption_check: bool = False,
    context: str = "declared",
) -> UndercutVerdict:
    """攻撃が、対象の仮定（assumptions のどれか）の否定を確立しているかを判定する.

    assumptions が空なら、LLM を呼ばずに、成立しない（仮定がなければ undercut しようがない）。
    context は、この判定が、何のためかの印（declared=宣言された undercut、ほか）。
    判定の理由は、run の記録に残す。
    """
    if not assumptions:
        return UndercutVerdict(False, None, "the target has no assumption to undercut")
    out: UndercutJudgement = await _ask(
        undercut_prompt(
            state, attack, target, assumptions, presumption_check=presumption_check
        ),
        UndercutJudgement,
        "undercut",
    )
    number = out.undercut_assumption_number
    chosen = (
        assumptions[number - 1]
        if isinstance(number, int)
        and not isinstance(number, bool)
        and 1 <= number <= len(assumptions)
        else None
    )
    record_judgement(
        {
            "kind": "undercut",
            "context": context,
            "attack_id": attack.id,
            "target_id": target.id,
            "assumptions": list(assumptions),
            "holds": chosen is not None,
            "assumption": chosen,
            "attack_conclusion_quote": out.attack_conclusion_quote,
            "reason": out.reason,
        }
    )
    return UndercutVerdict(
        chosen is not None, chosen, out.reason, out.attack_conclusion_quote
    )


async def assumptions_for(state: Any, record: ArgumentRecord) -> list[str]:
    """論証の仮定の一覧。schema は Ass、no_schema は、本文に明示された例外条項（引用）."""
    if is_schema(_mode(state)):
        return record.assumptions
    cached = _presumption_cache.get(record.id)
    if cached is not None:
        return cached
    out: PresumptionList = await _ask(extract_prompt(record), PresumptionList, "extract")
    text = record.argument
    found = [
        item.strip()
        for item in out.presumptions
        if item.strip() and item.strip() in text
    ]
    record_judgement(
        {
            "kind": "extract",
            "argument_id": record.id,
            "presumptions": found,
            "dropped_not_verbatim": [
                item for item in out.presumptions if item.strip() and item.strip() not in text
            ],
        }
    )
    _presumption_cache[record.id] = found
    return found


async def undercut_relation(
    state: Any,
    attack: ArgumentRecord,
    target: ArgumentRecord,
    context: str = "relation",
) -> UndercutVerdict:
    """U(attack, target): attack の結論のどれかが、target の仮定のどれかを否定しているか（宣言なしの一般の関係）."""
    return await judge_undercut(
        state,
        attack,
        target,
        await assumptions_for(state, target),
        context=context,
    )
