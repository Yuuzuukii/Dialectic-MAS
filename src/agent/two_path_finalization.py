"""Two-path finalization shared by schema and no-schema Dialectic-MAS.

Path A: if a main argument is justified, keep the existing justified-argument finalization.
Path B: if no main argument is justified, ignore partial intermediate synthesis state and
freshly synthesize the entire dialogue, then generate the final answer from that synthesis.

The policy is deliberately identical for ``schema`` and ``no_schema`` so experiments differ
only in argument representation, not in how unresolved debates are finalized.
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from .llm import chat_text

SUPPORTED_METHODS = {"schema", "no_schema"}

_FALLBACK_SYNTHESIS_SYSTEM = """<role>
You are a neutral synthesis operator.
</role>

<task>
The debate did not reach a justified main argument within the available dialogue budget.
Synthesize the entire debate into one integrated resolution that can serve as the sole basis
for the final answer.
</task>

<principles>
- Use the full dialogue, not only the latest main argument or a previously cached integrated rule.
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

_FALLBACK_FINAL_SYSTEM = """<role>
You are a neutral answer writer.
</role>

<task>
Answer the original question using the provided integrated synthesis as the primary and
controlling basis. Do not re-judge the debate or independently select a winning side.
</task>

<requirements>
- Lead with a direct answer to the original question.
- Preserve the synthesis's conditions, qualifications, unresolved points, and tradeoffs.
- Do not mention agents, turns, the debate process, justification status, fallback logic, or
  internal protocol terms.
- Do not silently discard one side's material requirements simply to make the answer more decisive.
- If the synthesis is conditional, the final answer may also be conditional rather than forcing an
  artificial unconditional yes/no conclusion.
</requirements>"""


def _dialogue_json(dialogue_history: list[dict[str, Any]]) -> str:
    return json.dumps(dialogue_history, ensure_ascii=False, indent=2)


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
    """Freshly synthesize the full unresolved dialogue in one neutral pass."""
    user = f"""Question:
{question}

AG1 stance:
{agent1_stance}

AG2 stance:
{agent2_stance}

Full dialogue history:
{_dialogue_json(dialogue_history)}
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
            "two-path fallback re-finalization supports only schema and no_schema logs; "
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
