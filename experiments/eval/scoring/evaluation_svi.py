"""Subjective Value Inventory (SVI) based first-person evaluation.

The questionnaire text is intentionally supplied by the caller rather than embedded here.
This keeps the evaluator reusable and lets the research code use an authorized copy of the
instrument without mixing questionnaire wording into the evaluation logic.

For each log, AG1 and AG2 independently answer the same 16 items from their own stance,
with the full debate transcript and final answer available as context.  Output shape is
constrained with Pydantic/with_structured_output: item number, 1-7 score (or None for NA),
and a short reason.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator

from .evaluation import build_eval_input


class SVIItemResponse(BaseModel):
    """One questionnaire response."""

    item: int = Field(ge=1, le=16)
    score: int | None = Field(default=None, ge=1, le=7)
    reason: str


class SVIEvaluation(BaseModel):
    """All 16 SVI responses for one agent."""

    responses: list[SVIItemResponse]

    @model_validator(mode="after")
    def validate_items(self) -> "SVIEvaluation":
        item_numbers = [response.item for response in self.responses]
        if item_numbers != list(range(1, 17)):
            raise ValueError("responses must contain items 1..16 exactly once, in order")
        return self


SVI_INSTRUCTION = """
You are one of the two agents who participated in the following discussion.

You will be given your original stance, the other agent's stance, the discussion history,
and the final answer.

Please answer the questionnaire from your own perspective as {agent}, based on how you
perceive the outcome of the discussion. Answer each question independently. If a question
is not applicable, use NA (represented as a null score).

Topic:
{topic}

Your stance:
{stance}

Other agent's stance:
{other_stance}

Discussion history:
{transcript}

Final answer:
{final_answer}

Questionnaire:
{questionnaire}

For each question, provide the item number, a score from 1 to 7 (or NA), and a brief reason.
""".strip()


def _format_questionnaire(items: list[str]) -> str:
    if len(items) != 16:
        raise ValueError(f"SVI questionnaire must contain exactly 16 items, got {len(items)}")
    return "\n".join(f"{index}. {text.strip()}" for index, text in enumerate(items, start=1))


def _judge_one(
    *,
    agent: str,
    stance: str,
    other_stance: str,
    topic: str,
    transcript: str,
    final_answer: str,
    questionnaire: str,
    judge_model: Any,
) -> list[dict[str, Any]]:
    prompt = SVI_INSTRUCTION.format(
        agent=agent,
        topic=topic,
        stance=stance,
        other_stance=other_stance,
        transcript=transcript,
        final_answer=final_answer,
        questionnaire=questionnaire,
    )
    structured_model = judge_model.with_structured_output(SVIEvaluation)
    result = structured_model.invoke(prompt)
    if not isinstance(result, SVIEvaluation):
        result = SVIEvaluation.model_validate(result)
    return [response.model_dump() for response in result.responses]


def evaluate_svi(
    log: dict[str, Any],
    judge_model: Any,
    items: list[str],
) -> dict[str, Any]:
    """Evaluate one debate log with all 16 SVI items for both agents.

    This function deliberately returns raw item-level responses only. Reverse scoring,
    subscale aggregation, bilateral aggregation, and any threshold for "agreement" are
    analysis decisions and are kept out of the evaluator itself.
    """
    eval_input = build_eval_input(log)
    final_answer = eval_input["final_answer"]
    transcript = eval_input["debate_transcript"]
    ag1_stance = eval_input["agent1_stance"]
    ag2_stance = eval_input["agent2_stance"]
    topic = str(log.get("question") or log.get("topic") or "(not provided)")
    questionnaire = _format_questionnaire(items)

    if (
        final_answer == "(no final answer)"
        or ag1_stance == "(not provided)"
        or ag2_stance == "(not provided)"
    ):
        return {"agent1": None, "agent2": None}

    ag1_result = _judge_one(
        agent="AG1",
        stance=ag1_stance,
        other_stance=ag2_stance,
        topic=topic,
        transcript=transcript,
        final_answer=final_answer,
        questionnaire=questionnaire,
        judge_model=judge_model,
    )
    ag2_result = _judge_one(
        agent="AG2",
        stance=ag2_stance,
        other_stance=ag1_stance,
        topic=topic,
        transcript=transcript,
        final_answer=final_answer,
        questionnaire=questionnaire,
        judge_model=judge_model,
    )

    return {"agent1": ag1_result, "agent2": ag2_result}


__all__ = [
    "SVIEvaluation",
    "SVIItemResponse",
    "SVI_INSTRUCTION",
    "evaluate_svi",
]
