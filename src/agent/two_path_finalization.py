"""Two-path finalization shared by schema, no-schema and free-debate.

Path A: if a main argument is justified, keep the existing justified-argument finalization
(schema / no_schema only: the other protocols have no notion of a justified argument).
Path B: otherwise, ignore partial intermediate synthesis state and freshly synthesize the
entire dialogue, then generate the final answer from that synthesis.

Path B is deliberately identical for every method, including the prompts and the way the
dialogue is rendered (:mod:`src.agent.dialogue_transcript`), so experiments differ only in the
debate itself, not in how an unresolved debate is finalized.
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from .dialogue_transcript import TRANSCRIPT_DESCRIPTION, format_transcript
from .llm import chat_text

SUPPORTED_METHODS = {"schema", "no_schema", "free_debate"}

# ログ（dialogue_history）に残す発話のフィールド。最終化の入力もこの形に揃える
# （生成中の finalize と、ログからの後付け refinalize で同じ入力になるように）。
SPEECH_LOG_KEYS = (
    "id",
    "agent",
    "proponent",
    "type",
    "argument",
    "attack",
    "target_id",
    "target_field",
    "target_statement",
    "status",
    "closed_by_budget",
)


def speech_log(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """対話履歴から、評価・分析・最終化に必要なフィールドだけを抜き出す."""
    return [
        {k: record.get(k) for k in SPEECH_LOG_KEYS if record.get(k) is not None}
        for record in history
    ]

_FALLBACK_SYNTHESIS_SYSTEM = """<task>
Synthesize the entire debate into one integrated resolution that can serve as the sole basis
for the final answer.
</task>

<principles>
- Use the full dialogue, not only its latest turns.
- Preserve every material requirement, value, condition, affected group, exception, threshold,
  and tradeoff from both original stances that remains relevant after the debate.
- Do not choose a winner merely because one side appears better supported overall.
- Resolve compatible points into a shared rule or policy bundle.
- When the sides support different outcomes under different conditions, state a conditional
  decision rule that preserves both mappings.
- If a conflict genuinely remains unresolved, state exactly what remains unresolved instead of
  silently breaking the tie in favor of one side.
- Produce a substantive synthesis, not a summary of who said what.
</principles>

<output>
Return only the integrated synthesis that should govern the final answer.
</output>"""

_FALLBACK_FINAL_SYSTEM = """<task>
Answer the original question using the provided integrated synthesis as the primary and
controlling basis. Do not re-judge the debate or independently select a winning side.
</task>

<requirements>
- Lead with a direct answer to the original question.
- Preserve the synthesis's conditions, qualifications, unresolved points, and tradeoffs.
- Do not mention agents, turns, or the debate process.
- Do not silently discard one side's material requirements simply to make the answer more decisive.
- If the synthesis is conditional, the final answer may also be conditional rather than forcing an
  artificial unconditional yes/no conclusion.
</requirements>"""


def _is_justified_path(log: dict[str, Any]) -> bool:
    """Return True only when the original run ended via a justified argument."""
    if log.get("consensus_reached") is True:
        return True
    status = str(log.get("justification_status") or "")
    return status in {"justified", "justified_argument"}


async def synthesize_unresolved_dialogue(
    *,
    question: str,
    agent1_stance: str,
    agent2_stance: str,
    dialogue_history: list[dict[str, Any]],
    model: str | None = None,
) -> str:
    """Freshly synthesize the full dialogue in one neutral pass.

    The dialogue is rendered the same way for every method (see ``format_transcript``): turn
    number, speaker and what each turn responds to, with no method-specific labels.
    """
    user = f"""Question:
{question}

AG1 stance:
{agent1_stance}

AG2 stance:
{agent2_stance}

Dialogue:
{TRANSCRIPT_DESCRIPTION}

{format_transcript(dialogue_history)}
""".strip()
    return (
        await chat_text(
            [
                SystemMessage(content=_FALLBACK_SYNTHESIS_SYSTEM),
                HumanMessage(content=user),
            ],
            model=model,
            verbosity="high",
        )
    ).strip()


async def answer_from_fallback_synthesis(
    *,
    question: str,
    agent1_stance: str,
    agent2_stance: str,
    synthesis: str,
    model: str | None = None,
) -> str:
    """Generate the user-facing answer from the fresh fallback synthesis only."""
    user = f"""Question:
{question}

AG1 stance:
{agent1_stance}

AG2 stance:
{agent2_stance}

Integrated synthesis:
{synthesis}
""".strip()
    return (
        await chat_text(
            [
                SystemMessage(content=_FALLBACK_FINAL_SYSTEM),
                HumanMessage(content=user),
            ],
            model=model,
            verbosity="high",
        )
    ).strip()


async def refinalize_unresolved_log(
    log: dict[str, Any], *, model: str | None = None
) -> dict[str, Any]:
    """Apply the shared two-path policy while preserving the dialogue unchanged."""
    method = str(log.get("method") or "")
    if method not in SUPPORTED_METHODS:
        raise ValueError(
            f"two-path fallback re-finalization supports only {sorted(SUPPORTED_METHODS)} logs; "
            f"got {method!r}"
        )

    if _is_justified_path(log):
        copied = dict(log)
        copied["finalization_path"] = "justified_argument"
        return copied

    dialogue_history = list(log.get("dialogue_history") or [])
    synthesis = await synthesize_unresolved_dialogue(
        question=str(log.get("question", "")),
        agent1_stance=str(log.get("agent1_stance", "")),
        agent2_stance=str(log.get("agent2_stance", "")),
        dialogue_history=dialogue_history,
        model=model,
    )
    answer = await answer_from_fallback_synthesis(
        question=str(log.get("question", "")),
        agent1_stance=str(log.get("agent1_stance", "")),
        agent2_stance=str(log.get("agent2_stance", "")),
        synthesis=synthesis,
        model=model,
    )

    copied = dict(log)
    copied["previous_final_answer"] = log.get("final_answer")
    copied["fallback_synthesis"] = synthesis
    copied["final_answer"] = answer
    copied["finalization_path"] = "fallback_full_dialogue_synthesis"
    copied["justification_status"] = "fallback_full_dialogue_synthesis"
    copied["consensus_reached"] = False
    return copied
