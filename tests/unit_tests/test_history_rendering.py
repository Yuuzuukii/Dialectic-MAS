"""履歴を LLM 用メッセージ列にするとき、過去の手番への指示を持ち込まないことを確かめる."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from src.agent import arguments

pytestmark = pytest.mark.anyio


def _history() -> list[HumanMessage | AIMessage]:
    instruction = "Round 1. Construct your main argument. set can_generate=NO if it repeats"
    return [
        HumanMessage(content=instruction),
        AIMessage(content='{"agent": "AG1"}', name="AG1"),
        HumanMessage(content=instruction),
        AIMessage(content='{"agent": "AG2"}', name="AG2"),
    ]


def test_render_history_keeps_only_the_utterances() -> None:
    rendered = arguments.render_history(_history())

    assert [type(m) for m in rendered] == [AIMessage, AIMessage]
    assert [m.name for m in rendered] == ["AG1", "AG2"]


async def test_defeat_prompt_does_not_carry_other_turns_instructions() -> None:
    state = SimpleNamespace(
        question="Q?",
        agent1_stance="stance 1",
        agent2_stance="stance 2",
        debate_round=1,
        integrated_rules=[],
        output_mode="schema",
        current_argument=None,
        history=_history(),
    )
    target = cast("Any", SimpleNamespace(id="arg-x", agent="AG2", argument="{}"))

    messages = await arguments.build_attack_messages(state, "AG1", target, purpose="defeat")

    assert isinstance(messages[0], SystemMessage)
    # 手番への指示は最後の1つだけ（過去の「主張を作れ」は残らない）。
    humans = [m for m in messages if isinstance(m, HumanMessage)]
    assert len(humans) == 1
    assert messages[-1] is humans[0]
    assert "can_generate=NO" not in humans[0].content
