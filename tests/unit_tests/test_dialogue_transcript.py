"""最終回答の統合に渡す議論記録が、手法に依らず同じ形式で、手法固有のラベルを含まないことを確かめる."""

from __future__ import annotations

import json
from typing import Any

import pytest

from src.agent import two_path_finalization as finalization
from src.agent.dialogue_transcript import (
    TRANSCRIPT_DESCRIPTION,
    format_transcript,
    render_argument_text,
)

pytestmark = pytest.mark.anyio

_SCHEMA_ARGUMENT = json.dumps(
    {
        "Argument": {
            "rules": [
                {"antecedent": {"strong": ["Fact A holds."], "weak_negation": ["no evidence B"]}, "consequent": "Step one."},
                {"antecedent": {"strong": ["Step one."], "weak_negation": []}, "consequent": "Therefore the conclusion."},
            ],
            "Conc": ["Step one.", "Therefore the conclusion."],
            "Ass": ["no evidence B"],
        }
    }
)

_LEAK_WORDS = ("rebut", "undercut", "justified", "overruled", "defensible", "status", "target_statement", "closed_by_budget")


def test_schema_argument_is_rendered_as_prose() -> None:
    text = render_argument_text(_SCHEMA_ARGUMENT)

    assert "Fact A holds. So step one." in text
    assert "Therefore, the conclusion." in text
    assert "relies on the assumption that no evidence B" in text
    assert "{" not in text


def test_free_text_is_kept_as_is() -> None:
    assert render_argument_text("  plain text  ") == "plain text"


def test_schema_and_free_debate_labels_use_the_same_vocabulary() -> None:
    schema_history: list[dict[str, Any]] = [
        {"id": "a", "agent": "AG1", "type": "main", "argument": _SCHEMA_ARGUMENT, "status": "defensible"},
        {"id": "b", "agent": "AG2", "type": "defeat", "attack": "rebut", "target_id": "a", "target_statement": "x", "argument": "reply"},
        {"id": "c", "agent": "AG1", "type": "counter", "attack": "undercut", "target_id": "b", "argument": "again"},
        {"id": "d", "agent": "AG2", "type": "main", "argument": "second line"},
    ]
    free_history = [
        {"agent": "AG1", "round": 1, "argument": "first", "has_new_point": True},
        {"agent": "AG2", "round": 1, "argument": "second", "has_new_point": True},
    ]

    schema_text = format_transcript(schema_history)
    free_text = format_transcript(free_history)

    assert "[Turn 1] AG1 (new argument)" in schema_text
    assert "[Turn 2] AG2 (responding to [Turn 1])" in schema_text
    assert "[Turn 3] AG1 (responding to [Turn 2])" in schema_text
    assert "[Turn 4] AG2 (new argument)" in schema_text
    assert "[Turn 1] AG1 (new argument)" in free_text
    assert "[Turn 2] AG2 (responding to [Turn 1])" in free_text
    for word in _LEAK_WORDS:
        assert word not in schema_text.lower()
        assert word not in free_text.lower()


async def test_synthesis_prompts_are_method_neutral(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[list[Any]] = []

    async def fake_chat_text(messages: list[Any], **kwargs: Any) -> str:
        seen.append(messages)
        return "ok"

    monkeypatch.setattr(finalization, "chat_text", fake_chat_text)
    history = [{"agent": "AG1", "round": 1, "argument": "a", "has_new_point": True}]

    await finalization.synthesize_unresolved_dialogue(
        question="Q?", agent1_stance="A", agent2_stance="B", dialogue_history=history
    )
    await finalization.answer_from_fallback_synthesis(
        question="Q?", agent1_stance="A", agent2_stance="B", synthesis="s"
    )

    for messages in seen:
        system = messages[0].content.lower()
        assert "<role>" not in system
        assert "justified" not in system
        assert "main argument" not in system
    assert TRANSCRIPT_DESCRIPTION in seen[0][1].content


async def test_free_debate_final_answer_node_always_uses_the_unresolved_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.agent.free_debate as free_debate

    async def fake_synthesis(**kwargs: Any) -> str:
        assert kwargs["dialogue_history"][0]["agent"] == "AG1"
        return "synthesis"

    async def fake_answer(**kwargs: Any) -> str:
        assert kwargs["synthesis"] == "synthesis"
        return "answer"

    monkeypatch.setattr(free_debate, "synthesize_unresolved_dialogue", fake_synthesis)
    monkeypatch.setattr(free_debate, "answer_from_fallback_synthesis", fake_answer)
    state = free_debate.FreeDebateState(question="Q?", agent1_stance="A", agent2_stance="B")
    state.dialogue_history = [{"agent": "AG1", "round": 1, "argument": "a", "has_new_point": True}]

    update = await free_debate.generate_final_answer(state)

    assert update == {
        "final_answer": "answer",
        "fallback_synthesis": "synthesis",
        "finalization_path": "fallback_full_dialogue_synthesis",
    }
