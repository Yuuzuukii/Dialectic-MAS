from __future__ import annotations

from typing import Any

import pytest

from src.agent import two_path_finalization as finalization


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["schema", "no_schema"])
async def test_justified_path_keeps_existing_answer(
    monkeypatch: pytest.MonkeyPatch, method: str
) -> None:
    async def fail_chat_text(*args: Any, **kwargs: Any) -> str:
        raise AssertionError("LLM must not be called for an already justified result")

    monkeypatch.setattr(finalization, "chat_text", fail_chat_text)
    log = {
        "method": method,
        "question": "Q?",
        "agent1_stance": "A",
        "agent2_stance": "B",
        "dialogue_history": [],
        "consensus_reached": True,
        "justification_status": "ag1_main_justified",
        "final_answer": "existing justified answer",
    }

    result = await finalization.refinalize_unresolved_log(log)

    assert result["final_answer"] == "existing justified answer"
    assert result["finalization_path"] == "justified_argument"
    assert "previous_final_answer" not in result


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["schema", "no_schema"])
async def test_unresolved_path_synthesizes_then_answers(
    monkeypatch: pytest.MonkeyPatch, method: str
) -> None:
    calls: list[str] = []

    async def fake_chat_text(messages: list[Any], **kwargs: Any) -> str:
        system = messages[0].content
        calls.append(system)
        if "neutral synthesis operator" in system:
            assert "Full dialogue history" in messages[1].content
            return "balanced synthesis"
        assert "neutral answer writer" in system
        assert "balanced synthesis" in messages[1].content
        return "answer from synthesis"

    monkeypatch.setattr(finalization, "chat_text", fake_chat_text)
    log = {
        "method": method,
        "question": "Q?",
        "agent1_stance": "A",
        "agent2_stance": "B",
        "dialogue_history": [
            {"agent": "AG1", "argument": "a"},
            {"agent": "AG2", "argument": "b"},
        ],
        "consensus_reached": False,
        "justification_status": "fallback_no_consensus",
        "final_answer": "old best-supported answer",
        "integrated_rules": ["old partial rule that must not control the fresh synthesis"],
    }

    result = await finalization.refinalize_unresolved_log(log)

    assert len(calls) == 2
    assert result["previous_final_answer"] == "old best-supported answer"
    assert result["fallback_synthesis"] == "balanced synthesis"
    assert result["final_answer"] == "answer from synthesis"
    assert result["finalization_path"] == "fallback_full_dialogue_synthesis"
    assert result["consensus_reached"] is False


@pytest.mark.asyncio
async def test_other_methods_are_rejected() -> None:
    with pytest.raises(ValueError, match="schema and no_schema"):
        await finalization.refinalize_unresolved_log({"method": "mad"})
