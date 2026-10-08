"""最終回答の共通の作り方（final_answer.py）のテスト.

材料は、議論全体（必ず）、justified な論証（あれば）、統合案（あれば）。
統合案の材料は各陣営の最後の主張で、どちらかの陣営に主張がなければ統合案は作らない。
"""

from __future__ import annotations

from typing import Any

import pytest

from src.agent import final_answer

pytestmark = pytest.mark.anyio


def _turn(agent: str, kind: str, text: str, tid: str) -> dict[str, Any]:
    return {"id": tid, "agent": agent, "type": kind, "argument": text}


HISTORY = [
    _turn("AG1", "main", "ag1 first main", "a"),
    _turn("AG2", "defeat", "ag2 rebuttal", "b"),
    _turn("AG1", "counter", "ag1 counter", "c"),
    _turn("AG1", "main", "ag1 second main", "d"),
    _turn("AG2", "main", "ag2 main", "e"),
    _turn("AG1", "defeat", "ag1 rebuttal to ag2 main", "f"),
]


def test_last_position_is_each_sides_last_main_not_last_turn() -> None:
    assert final_answer.last_position(HISTORY, "AG1") == "ag1 second main"
    assert final_answer.last_position(HISTORY, "AG2") == "ag2 main"


def test_last_position_is_none_when_a_side_has_no_main() -> None:
    history = HISTORY[:3]  # AG2 は反論しか出していない
    assert final_answer.last_position(history, "AG1") == "ag1 first main"
    assert final_answer.last_position(history, "AG2") is None


def test_last_position_without_types_is_last_statement() -> None:
    free = [
        {"agent": "AG1", "round": 1, "argument": "first"},
        {"agent": "AG2", "round": 1, "argument": "reply"},
        {"agent": "AG1", "round": 2, "argument": "last of ag1"},
    ]
    assert final_answer.last_position(free, "AG1") == "last of ag1"
    assert final_answer.last_position(free, "AG2") == "reply"


async def _run(
    monkeypatch: pytest.MonkeyPatch,
    history: list[dict[str, Any]],
    justified: str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    seen: dict[str, Any] = {}

    async def fake_integrate(**kwargs: Any) -> str:
        seen["integrate"] = kwargs
        return "integrated proposal"

    async def fake_chat_text(messages: list[Any], **kwargs: Any) -> str:
        seen["system"] = messages[0].content
        seen["user"] = messages[1].content
        return "final answer"

    monkeypatch.setattr(final_answer, "integrate_positions", fake_integrate)
    monkeypatch.setattr(final_answer, "chat_text", fake_chat_text)
    result = await final_answer.finalize(
        question="Q?",
        agent1_stance="A",
        agent2_stance="B",
        dialogue_history=history,
        justified_argument=justified,
    )
    return result, seen


async def test_integrates_last_mains_then_answers_from_proposal_and_dialogue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, seen = await _run(monkeypatch, HISTORY, None)

    assert seen["integrate"]["position1"] == "ag1 second main"
    assert seen["integrate"]["position2"] == "ag2 main"
    assert result["finalization_path"] == final_answer.PATH_INTEGRATED
    assert result["integrated_proposal"] == "integrated proposal"
    assert result["final_answer"] == "final answer"
    assert "Integrated proposal:\nintegrated proposal" in seen["user"]
    assert "ag1 rebuttal to ag2 main" in seen["user"]  # 議論全体が渡る
    assert "Justified argument" not in seen["user"]


async def test_justified_argument_skips_integration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, seen = await _run(monkeypatch, HISTORY, "the justified one")

    assert "integrate" not in seen
    assert result["finalization_path"] == final_answer.PATH_JUSTIFIED
    assert result["integrated_proposal"] is None
    assert "Justified argument:\nthe justified one" in seen["user"]
    assert "Integrated proposal" not in seen["user"]
    assert "ag2 main" in seen["user"]


async def test_side_without_main_gets_dialogue_only_with_the_same_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, seen = await _run(monkeypatch, HISTORY[:3], None)

    assert "integrate" not in seen
    assert result["finalization_path"] == final_answer.PATH_DIALOGUE_ONLY
    assert result["integrated_proposal"] is None
    assert "Integrated proposal" not in seen["user"]
    assert "ag2 rebuttal" in seen["user"]
    # プロンプトは3つの場合で同じ（あれば参照する、という書き方）
    assert "If an integrated proposal is provided" in seen["system"]
    assert "If a justified argument is provided" in seen["system"]


async def test_node_uses_justified_argument_and_dialogue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import agent.nodes as nodes_module
    from agent.workflow import State

    captured: dict[str, Any] = {}

    async def fake_finalize(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {
            "final_answer": "ans",
            "integrated_proposal": None,
            "finalization_path": "p",
        }

    monkeypatch.setattr(nodes_module, "finalize_answer", fake_finalize)
    state = State(question="Q?", agent1_stance="A", agent2_stance="B")
    state.consensus_reached = True
    state.justified_argument = "arg"

    update = await nodes_module.generate_final_answer(state)

    assert captured["justified_argument"] == "arg"
    assert update["final_answer"] == "ans"
    assert update["consensus_reached"] is True


async def test_node_without_justified_argument_passes_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import agent.nodes as nodes_module
    from agent.workflow import State

    captured: dict[str, Any] = {}

    async def fake_finalize(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {
            "final_answer": "ans",
            "integrated_proposal": "x",
            "finalization_path": "p",
        }

    monkeypatch.setattr(nodes_module, "finalize_answer", fake_finalize)
    state = State(question="Q?", agent1_stance="A", agent2_stance="B")
    state.consensus_reached = False
    state.justified_argument = (
        "a stale fallback base"  # finalize_fallback が入れる値は使わない
    )

    update = await nodes_module.generate_final_answer(state)

    assert captured["justified_argument"] is None
    assert update["consensus_reached"] is False
    assert update["integrated_proposal"] == "x"
