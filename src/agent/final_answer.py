"""最終回答の作り方（schema / no_schema / free_debate / MAD の統合版で共通）.

材料は次の3つで、手法に依らず同じ形・同じプロンプトで渡す。

1. 議論全体の記録（:mod:`src.agent.dialogue_transcript` の中立な書き起こし）。必ず渡す。
2. justified な論証。議論が決着した（justified の主張がある）ときだけ渡す。
3. 統合案。各陣営の最後の主張から作る。どちらかの陣営に主張がなければ作らず、渡さない。

統合案は Kido & Kurihara の汎化・統合（対立する2者の立場 A, B から、双方を含む C を作る）に
合わせ、材料を「各陣営の最後の主張」にしている。議論の木を持つ手法（schema / no_schema）は
陣営ごとの最後の main、持たない手法（free_debate / MAD）は陣営ごとの最後の発言を使う。

最終回答のプロンプトは3つの場合（justified あり / 統合案あり / 議論のみ）で同じ1つで、
「渡されている場合は、参照する」という書き方にしている。
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from .arguments import generate_integration
from .dialogue_transcript import (
    TRANSCRIPT_DESCRIPTION,
    format_transcript,
    render_argument_text,
)
from .llm import chat_text

PATH_JUSTIFIED = "justified_with_dialogue"
PATH_INTEGRATED = "integrated_with_dialogue"
PATH_DIALOGUE_ONLY = "dialogue_only"

_FINAL_SYSTEM = """<task>
Answer the original question, using the record of the debate between AG1 and AG2.
</task>

<materials>
- The dialogue: always provided. It shows everything both sides argued and how each side responded.
- A justified argument: provided only when the debate reached one. It is an argument that stood
  against every objection raised in the dialogue.
- An integrated proposal: provided only when both sides had a final position to integrate. It is a
  single proposal built from the two sides' final positions.
</materials>

<requirements>
- Lead with a direct answer to the original question.
- If a justified argument is provided, refer to it: it is the conclusion the debate reached.
- If an integrated proposal is provided, refer to it: treat it as the primary basis of the answer.
- Use the dialogue to keep what each side raised and what the other side answered. Preserve every
  material requirement, value, condition, affected group, exception, and tradeoff from both
  stances that remains relevant after the debate.
- Do not independently select a winning side, and do not silently discard one side's material
  requirements simply to make the answer more decisive.
- If the basis you were given is conditional, the final answer may also be conditional rather than
  forcing an artificial unconditional yes/no conclusion. If a conflict genuinely remains
  unresolved, state exactly what remains unresolved.
- Do not mention agents, turns, or the debate process.
</requirements>"""


_WRITER_ROLE = """<role>
You are {writer} in this debate. The stance labeled "{writer} stance" below is yours. You now write the final answer
to the original question.
</role>

"""


def final_system(writer: str | None = None) -> str:
    """最終回答のシステムプロンプトを返す。writer（例: "AG1"）を渡すと、その陣営の役割で書かせる."""
    return (
        _FINAL_SYSTEM
        if writer is None
        else _WRITER_ROLE.format(writer=writer) + _FINAL_SYSTEM
    )


def last_position(dialogue_history: list[dict[str, Any]], agent: str) -> str | None:
    """その陣営の最後の主張を、読める文章で返す（なければ None）.

    発話が ``type`` を持つ手法（schema / no_schema）は、その陣営が最後に出した main。
    持たない手法（free_debate / MAD）は、その陣営の最後の発言。
    """
    has_type = any("type" in turn for turn in dialogue_history)
    for turn in reversed(dialogue_history):
        if turn.get("agent") != agent:
            continue
        if has_type and turn.get("type") != "main":
            continue
        return render_argument_text(turn.get("argument"))
    return None


async def integrate_positions(
    *,
    agent1_stance: str,
    agent2_stance: str,
    position1: str,
    position2: str,
) -> str | None:
    """2つの陣営の最後の主張から、統合案（共通の統合プロンプトの出力）を1つ作る."""
    warrants = json.dumps(
        {
            "Argument1": {"agent": "AG1", "warrant": position1},
            "Argument2": {"agent": "AG2", "warrant": position2},
        },
        ensure_ascii=False,
    )
    state = SimpleNamespace(
        warrant_result=warrants,
        agent1_stance=agent1_stance,
        agent2_stance=agent2_stance,
        output_mode="no_schema",
    )
    output = await generate_integration(state)
    argument = output.model_dump(exclude_none=True).get("Argument")
    rule = argument.get("rule") if isinstance(argument, dict) else None
    return rule.strip() if isinstance(rule, str) and rule.strip() else None


def _final_user(
    *,
    question: str,
    agent1_stance: str,
    agent2_stance: str,
    dialogue_history: list[dict[str, Any]],
    integrated_proposal: str | None,
    justified_argument: str | None,
) -> str:
    blocks = [
        f"Question:\n{question}",
        f"AG1 stance:\n{agent1_stance}",
        f"AG2 stance:\n{agent2_stance}",
    ]
    if justified_argument:
        blocks.append(
            f"Justified argument:\n{render_argument_text(justified_argument)}"
        )
    if integrated_proposal:
        blocks.append(f"Integrated proposal:\n{integrated_proposal}")
    blocks.append(
        f"Dialogue:\n{TRANSCRIPT_DESCRIPTION}\n\n{format_transcript(dialogue_history)}"
    )
    return "\n\n".join(blocks).strip()


async def answer_from_materials(
    *,
    question: str,
    agent1_stance: str,
    agent2_stance: str,
    dialogue_history: list[dict[str, Any]],
    integrated_proposal: str | None = None,
    justified_argument: str | None = None,
    model: str | None = None,
    writer: str | None = None,
) -> str:
    """議論全体と、（あれば）justified な論証・統合案から、最終回答を作る.

    writer が None なら中立な書き手（既定）。"AG1" などを渡すと、その陣営の役割で書く（立場文は、ユーザー側に
    「AG1 stance」として、どちらの場合も渡している）。
    """
    user = _final_user(
        question=question,
        agent1_stance=agent1_stance,
        agent2_stance=agent2_stance,
        dialogue_history=dialogue_history,
        integrated_proposal=integrated_proposal,
        justified_argument=justified_argument,
    )
    return (
        await chat_text(
            [SystemMessage(content=final_system(writer)), HumanMessage(content=user)],
            model=model,
            verbosity="high",
        )
    ).strip()


async def finalize(
    *,
    question: str,
    agent1_stance: str,
    agent2_stance: str,
    dialogue_history: list[dict[str, Any]],
    justified_argument: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """最終回答を作り、使った材料と経路を返す.

    - justified な論証があれば、統合案は作らず、その論証と議論全体から作る。
    - なければ、両陣営の最後の主張から統合案を作り、統合案と議論全体から作る。
    - どちらかの陣営に主張がなければ、統合案は作らず、議論全体だけから作る。
    """
    integrated: str | None = None
    if justified_argument:
        path = PATH_JUSTIFIED
    else:
        position1 = last_position(dialogue_history, "AG1")
        position2 = last_position(dialogue_history, "AG2")
        if position1 and position2:
            integrated = await integrate_positions(
                agent1_stance=agent1_stance,
                agent2_stance=agent2_stance,
                position1=position1,
                position2=position2,
            )
        path = PATH_INTEGRATED if integrated else PATH_DIALOGUE_ONLY
    answer = await answer_from_materials(
        question=question,
        agent1_stance=agent1_stance,
        agent2_stance=agent2_stance,
        dialogue_history=dialogue_history,
        integrated_proposal=integrated,
        justified_argument=justified_argument,
        model=model,
    )
    return {
        "final_answer": answer,
        "integrated_proposal": integrated,
        "finalization_path": path,
    }
