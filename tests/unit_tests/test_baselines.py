"""比較手法（free_debate / mad / mad_synthesis）の流れを、LLM なしで確認するテスト."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from src.agent_migration.argumentation.dialectical import AG1, AG2, Result
from src.agent_migration.argumentation.free_debate import DebateTurn, FreeDebate
from src.agent_migration.argumentation.mad import MAD
from src.agent_migration.argumentation.mad_judge import MAD_JUDGE_SYSTEM


def turn(text: str, new: bool = True) -> DebateTurn:
    return DebateTurn(argument=text, has_new_point=new)


class FakeDebater:
    """structured() は、DebateTurn を順に返す。chat() は、プロンプトの種類で、決まった文章を返す。"""

    def __init__(self, turns: list[DebateTurn]) -> None:
        self.turns = list(turns)
        self.structured_calls: list[dict[str, Any]] = []
        self.chat_calls: list[dict[str, Any]] = []

    async def structured(self, prompt: str, schema: Any, system: str | None = None) -> Any:
        self.structured_calls.append({"prompt": prompt, "schema": schema, "system": system})
        assert schema is DebateTurn
        return self.turns.pop(0)

    async def chat(self, prompt: str, system: str | None = None) -> Any:
        self.chat_calls.append({"prompt": prompt, "system": system})
        if "Create a new strict rule C" in prompt:
            return SimpleNamespace(content="RULE C")
        if "You created this new strict rule" in prompt:
            return SimpleNamespace(content="NEW MAIN")
        if prompt.startswith("Now the argumentation is over"):
            return SimpleNamespace(content="FINAL ANSWER")
        if system is not None and system.startswith("<role>\nYou are an independent judge"):
            return SimpleNamespace(content="JUDGE ANSWER")
        raise AssertionError(prompt)


class FakeHelper:
    """判定用。できないとは言わない。warrant は、渡された文章に印を付けて返す。"""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def chat(self, prompt: str, system: str | None = None) -> Any:
        self.calls.append(prompt)
        assert system is None
        if prompt.startswith("The following is an agent's reply."):
            return SimpleNamespace(content="No.")
        if prompt.startswith("Argument:\n"):
            return SimpleNamespace(content="WARRANT OF: " + prompt.split("Argument:\n", 1)[1].split("\n\nWrite the warrant")[0])
        raise AssertionError(prompt)


def make(cls: type[FreeDebate], ag1: FakeDebater, ag2: FakeDebater, max_turns: int, helper: FakeHelper, **kw: Any) -> FreeDebate:
    return cls(ag1, ag2, issue="ISSUE", theory1="THEORY1", theory2="THEORY2", max_turns=max_turns, judge=helper, **kw)  # type: ignore[arg-type]


def run(debate: FreeDebate) -> Result:
    result = asyncio.run(debate.run())
    print("\n" + "\n".join(result.trace))  # noqa: T201
    return result


def test_free_debate_alternates_and_stops_at_the_turn_limit_then_integrates() -> None:
    ag1 = FakeDebater([turn("A1"), turn("A2")])
    ag2 = FakeDebater([turn("B1"), turn("B2")])
    helper = FakeHelper()
    r = run(make(FreeDebate, ag1, ag2, 4, helper))
    assert [m.role for m in r.history][:4] == [AG1, AG2, AG1, AG2]
    assert [m.kind for m in r.history] == ["turn"] * 4 + ["integrate", "main"]
    assert r.turns == 4 and r.closed_by == "turn_limit"
    # 統合: 各陣営の最後の発言（A2 と B2）を、warrant として渡す
    integrate_call = next(c for c in ag1.chat_calls if "Create a new strict rule C" in c["prompt"])
    assert "WARRANT OF: A2" in integrate_call["prompt"] and "WARRANT OF: B2" in integrate_call["prompt"]
    # 最終回答: justified なしの文。履歴の地位は、統合から出した主張だけに付く（発言には付かない）
    final = ag1.chat_calls[-1]
    assert final["prompt"].startswith("Now the argumentation is over, but no argument was justified.")
    assert final["system"].count('"status"') == 1
    assert r.final_answer == "FINAL ANSWER" and r.statuses == {5: "defensible"}


def test_free_debate_prompts() -> None:
    ag1, ag2 = FakeDebater([turn("A1")]), FakeDebater([turn("B1")])
    run(make(FreeDebate, ag1, ag2, 2, FakeHelper()))
    first, second = ag1.structured_calls[0], ag2.structured_calls[0]
    assert first["prompt"] == "Question: ISSUE\n\nState your initial argument for your stance."
    assert first["system"].startswith('<identity>\nYou are agent 1 in this debate.')
    assert "THEORY1" in first["system"] and "<grounding>" in first["system"] and "The debate so far:\n[]" in first["system"]
    assert "THEORY2" in second["system"] and '"content": "A1"' in second["system"]
    assert "state your initial argument for your stance" in second["prompt"] and "argue against" not in second["prompt"]


def test_novelty_hint_from_round_two_and_early_stop_when_both_have_nothing_new() -> None:
    # 1ラウンド目は、定義上、新しい（False と答えても True）。2ラウンド目に、両者が False → 終わる。
    ag1 = FakeDebater([turn("A1", new=False), turn("A2", new=False), turn("A3")])
    ag2 = FakeDebater([turn("B1", new=False), turn("B2", new=False), turn("B3")])
    r = run(make(FreeDebate, ag1, ag2, 20, FakeHelper()))
    assert r.closed_by == "no_new_point" and r.turns == 4
    assert "has_new_point=false" not in ag1.structured_calls[0]["prompt"]
    assert "has_new_point=false" in ag1.structured_calls[1]["prompt"]


def test_one_side_having_a_new_point_keeps_the_debate_going() -> None:
    ag1 = FakeDebater([turn("A1"), turn("A2", new=False), turn("A3", new=False)])
    ag2 = FakeDebater([turn("B1"), turn("B2", new=True), turn("B3", new=False)])
    r = run(make(FreeDebate, ag1, ag2, 20, FakeHelper()))
    assert r.turns == 6 and r.closed_by == "no_new_point"


def test_mad_asks_to_argue_against() -> None:
    ag1, ag2 = FakeDebater([turn("A1"), turn("A2")]), FakeDebater([turn("B1"), turn("B2")])
    run(make(MAD, ag1, ag2, 4, FakeHelper(), use_synthesis=True))
    assert "argue against it" in ag2.structured_calls[0]["prompt"]
    assert "agent 2's latest argument" in ag1.structured_calls[1]["prompt"] and "argue against it" in ag1.structured_calls[1]["prompt"]


def test_mad_with_a_judge_writes_the_answer_without_integration() -> None:
    ag1, ag2 = FakeDebater([turn("A1")]), FakeDebater([turn("B1")])
    judge_agent = FakeDebater([])
    helper = FakeHelper()
    r = run(make(MAD, ag1, ag2, 2, helper, use_synthesis=False, final_judge=judge_agent))  # type: ignore[arg-type]
    assert [m.kind for m in r.history] == ["turn", "turn"] and r.statuses == {}
    assert r.final_answer == "JUDGE ANSWER" and helper.calls == []  # 統合も、判定用の呼び出しもない
    call = judge_agent.chat_calls[0]
    assert call["system"] == MAD_JUDGE_SYSTEM
    assert call["prompt"].startswith("Question: ISSUE\n\nDialogue history:\n[") and '"content": "A1"' in call["prompt"]
    assert not any("Create a new strict rule C" in c["prompt"] for c in ag1.chat_calls)


def test_mad_with_a_judge_requires_the_judge_agent() -> None:
    with pytest.raises(ValueError):
        make(MAD, FakeDebater([]), FakeDebater([]), 2, FakeHelper(), use_synthesis=False)


def test_mad_synthesis_ends_like_free_debate() -> None:
    ag1, ag2 = FakeDebater([turn("A1")]), FakeDebater([turn("B1")])
    r = run(make(MAD, ag1, ag2, 2, FakeHelper(), use_synthesis=True))
    assert [m.kind for m in r.history] == ["turn", "turn", "integrate", "main"] and r.final_answer == "FINAL ANSWER"


def test_a_side_without_any_turn_is_not_integrated() -> None:
    # 上限が1: ag1 の発言だけ。ag2 の発言がないので、統合できない。最終回答は、書く。
    ag1, ag2 = FakeDebater([turn("A1")]), FakeDebater([])
    r = run(make(FreeDebate, ag1, ag2, 1, FakeHelper()))
    assert [m.kind for m in r.history] == ["turn"] and r.final_answer == "FINAL ANSWER"
    assert any("統合できない" in t for t in r.trace)
