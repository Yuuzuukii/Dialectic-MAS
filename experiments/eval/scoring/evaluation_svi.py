"""Subjective Value Inventory (SVI) based first-person evaluation.

This evaluator adapts the original SVI administration to the two-agent debate setting:
AG1 and AG2 independently answer all 16 items from their own perspective after seeing
both original stances, the full debate transcript, and the final answer.

SVI source:
Curhan, J. R., Elfenbein, H. A., & Xu, H. (2006). What do people value when they
negotiate? Mapping the domain of subjective value in negotiation. Journal of Personality
and Social Psychology, 91, 493-512.

The official SVI information sheet states that the instrument is free for non-commercial
research use. For a two-person negotiation it also recommends using singular
"counterpart" and "outcome" wording. Items are presented without subscale headings,
as recommended by the administration notes.
"""

from __future__ import annotations

from statistics import mean
from typing import Any

from pydantic import BaseModel, Field, model_validator

from .evaluation import build_eval_input


class SVIItemResponse(BaseModel):
    """One SVI questionnaire response."""

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


# Official SVI item wording, adapted only as explicitly recommended for a two-person
# negotiation (counterpart(s) -> counterpart; outcome(s) -> outcome).
# Each tuple is: (item text, low anchor, midpoint anchor, high anchor).
SVI_ITEMS: tuple[tuple[str, str, str, str], ...] = (
    (
        "How satisfied are you with your own outcome—i.e., the extent to which the terms of your agreement (or lack of agreement) benefit you?",
        "Not at all",
        "Moderately",
        "Perfectly",
    ),
    (
        "How satisfied are you with the balance between your own outcome and your counterpart's outcome?",
        "Not at all",
        "Moderately",
        "Perfectly",
    ),
    (
        "Did you feel like you forfeited or ‘lost’ in this negotiation?",
        "Not at all",
        "Moderately",
        "A great deal",
    ),
    (
        "Do you think the terms of your agreement are consistent with principles of legitimacy or objective criteria (e.g., common standards of fairness, precedent, industry practice, legality, etc.)?",
        "Not at all",
        "Moderately",
        "Perfectly",
    ),
    (
        "Did you ‘lose face’ (i.e., damage your sense of pride) in the negotiation?",
        "Not at all",
        "Moderately",
        "A great deal",
    ),
    (
        "Did this negotiation make you feel more or less competent as a negotiator?",
        "It made me feel less competent",
        "It did not make me feel more or less competent",
        "It made me feel more competent",
    ),
    (
        "Did you behave according to your own principles and values?",
        "Not at all",
        "Moderately",
        "Perfectly",
    ),
    (
        "Did this negotiation positively or negatively impact your self-image or your impression of yourself?",
        "It negatively impacted my self-image",
        "It did not positively or negatively impact my self-image",
        "It positively impacted my self-image",
    ),
    (
        "Do you feel your counterpart listened to your concerns?",
        "Not at all",
        "Moderately",
        "Perfectly",
    ),
    (
        "Would you characterize the negotiation process as fair?",
        "Not at all",
        "Moderately",
        "Perfectly",
    ),
    (
        "How satisfied are you with the ease (or difficulty) of reaching an agreement?",
        "Not at all satisfied",
        "Moderately satisfied",
        "Perfectly satisfied",
    ),
    (
        "Did your counterpart consider your wishes, opinions, or needs?",
        "Not at all",
        "Moderately",
        "Perfectly",
    ),
    (
        "What kind of ‘overall’ impression did your counterpart make on you?",
        "Extremely negative",
        "Neither negative nor positive",
        "Extremely positive",
    ),
    (
        "How satisfied are you with your relationship with your counterpart as a result of this negotiation?",
        "Not at all",
        "Moderately",
        "Perfectly",
    ),
    (
        "Did the negotiation make you trust your counterpart?",
        "Not at all",
        "Moderately",
        "Perfectly",
    ),
    (
        "Did the negotiation build a good foundation for a future relationship with your counterpart?",
        "Not at all",
        "Moderately",
        "Perfectly",
    ),
)


SVI_INSTRUCTION = """
You are one of the two agents who participated in the following discussion.

You will be given your original stance, the other agent's stance, the discussion history,
and the final answer.

Please answer the questionnaire from your own perspective as {agent}, based on how you
perceive the outcome of the discussion. For each question, choose a number from 1 to 7
that most accurately reflects your opinion. Answer each question independently. If a
question is not applicable, use NA (represented as a null score).

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

For each question, provide the item number, score, and a brief reason.
""".strip()


def _format_questionnaire() -> str:
    lines: list[str] = []
    for index, (text, low, midpoint, high) in enumerate(SVI_ITEMS, start=1):
        lines.append(
            f"{index}. {text}\n"
            f"   1 = {low}; 4 = {midpoint}; 7 = {high}; NA = not applicable"
        )
    return "\n".join(lines)


def _judge_one(
    *,
    agent: str,
    stance: str,
    other_stance: str,
    topic: str,
    transcript: str,
    final_answer: str,
    judge_model: Any,
) -> list[dict[str, Any]]:
    prompt = SVI_INSTRUCTION.format(
        agent=agent,
        topic=topic,
        stance=stance,
        other_stance=other_stance,
        transcript=transcript,
        final_answer=final_answer,
        questionnaire=_format_questionnaire(),
    )
    structured_model = judge_model.with_structured_output(SVIEvaluation)
    result = structured_model.invoke(prompt)
    if not isinstance(result, SVIEvaluation):
        result = SVIEvaluation.model_validate(result)
    return [response.model_dump() for response in result.responses]


def score_svi(responses: list[dict[str, Any]] | None) -> dict[str, float | None]:
    """Aggregate raw SVI responses without reverse scoring.

    The evaluator preserves the model's original 1-7 response for every item, including
    items 3 and 5. Each four-item subscale is the equal-weight mean of the raw available
    responses. Any reverse scoring required for later statistical analysis is intentionally
    left to the downstream analysis step.
    """
    if not responses:
        return {
            "instrumental": None,
            "self": None,
            "process": None,
            "relationship": None,
            "global": None,
            "rapport": None,
        }

    raw_by_item: dict[int, int | None] = {
        int(response["item"]): response.get("score") for response in responses
    }

    def _mean_items(item_numbers: range) -> float | None:
        values = [raw_by_item[item] for item in item_numbers if raw_by_item.get(item) is not None]
        return mean(values) if values else None

    instrumental = _mean_items(range(1, 5))
    self_score = _mean_items(range(5, 9))
    process = _mean_items(range(9, 13))
    relationship = _mean_items(range(13, 17))
    subscales = [x for x in (instrumental, self_score, process, relationship) if x is not None]
    rapport_parts = [x for x in (process, relationship) if x is not None]

    return {
        "instrumental": instrumental,
        "self": self_score,
        "process": process,
        "relationship": relationship,
        "global": mean(subscales) if subscales else None,
        "rapport": mean(rapport_parts) if rapport_parts else None,
    }


def evaluate_svi(log: dict[str, Any], judge_model: Any) -> dict[str, Any]:
    """Evaluate one debate log with all 16 SVI items for both agents."""
    eval_input = build_eval_input(log)
    final_answer = eval_input["final_answer"]
    transcript = eval_input["debate_transcript"]
    ag1_stance = eval_input["agent1_stance"]
    ag2_stance = eval_input["agent2_stance"]
    topic = str(log.get("question") or log.get("topic") or "(not provided)")

    if (
        final_answer == "(no final answer)"
        or ag1_stance == "(not provided)"
        or ag2_stance == "(not provided)"
    ):
        return {"agent1": None, "agent2": None, "agent1_scores": None, "agent2_scores": None}

    ag1_result = _judge_one(
        agent="AG1",
        stance=ag1_stance,
        other_stance=ag2_stance,
        topic=topic,
        transcript=transcript,
        final_answer=final_answer,
        judge_model=judge_model,
    )
    ag2_result = _judge_one(
        agent="AG2",
        stance=ag2_stance,
        other_stance=ag1_stance,
        topic=topic,
        transcript=transcript,
        final_answer=final_answer,
        judge_model=judge_model,
    )

    return {
        "agent1": ag1_result,
        "agent2": ag2_result,
        "agent1_scores": score_svi(ag1_result),
        "agent2_scores": score_svi(ag2_result),
    }


__all__ = [
    "SVIEvaluation",
    "SVIItemResponse",
    "SVI_ITEMS",
    "SVI_INSTRUCTION",
    "evaluate_svi",
    "score_svi",
]
