from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from agent.edges import route_after_can_generate_main
from agent.nodes import can_generate_main
from agent.prompt_builders import build_main_argument_messages
from agent.schema.llm_outputs import ArgumentBody
from agent.schema.state import ArgumentRecord
from agent.workflow import State

pytestmark = pytest.mark.anyio


def argument_payload(consequent: str) -> str:
    return json.dumps(
        {
            "Argument": {
                "rules": [],
                "Conc": [consequent],
                "Ass": [],
            }
        }
    )


async def test_initial_main_messages_have_system_identity_and_round_instruction() -> None:
    prior = ArgumentRecord(
        type="main",
        argument=argument_payload("previous conclusion"),
        support=[],
        agent="AG1",
    )
    state = State(
        question="What should we choose?",
        agent1_stance="Your stance: choose A.",
        agent2_stance="",
        history=[prior],
    )

    messages = build_main_argument_messages(state, "AG1")

    assert isinstance(messages[0], SystemMessage)
    assert isinstance(messages[-1], HumanMessage)
    system = str(messages[0].content)
    assert "You are AG1" in system
    assert "<protocol_flow>" in system
    assert "<task>" in system

    # 履歴は全フェーズで与える → 過去の主張が AIMessage として含まれる。
    history_msgs = [m for m in messages if isinstance(m, AIMessage)]
    assert len(history_msgs) == 1
    assert history_msgs[0].name == "AG1"
    assert "previous conclusion" in str(history_msgs[0].content)

    instruction = str(messages[-1].content)
    assert "Round 1" in instruction
    assert "Issue: What should we choose?" in instruction
    assert "revision" not in instruction.lower()


async def test_revision_main_instruction_uses_integrated_rules_and_renders_history() -> None:
    prior_main = ArgumentRecord(
        type="main", argument=argument_payload("first main conclusion"), support=[], agent="AG1"
    )
    prior_counter = ArgumentRecord(
        type="counter", argument=argument_payload("previous counter conclusion"), support=[], agent="AG1"
    )
    recent_main = ArgumentRecord(
        type="main", argument=argument_payload("second main conclusion"), support=[], agent="AG1"
    )
    state = State(
        question="What should we choose?",
        agent1_stance="Your stance: choose A.",
        agent2_stance="",
        history=[prior_main, prior_counter, recent_main],
        integrated_rules=["shared condition -> proposed alternative"],
        debate_round=2,
    )

    messages = build_main_argument_messages(state, "AG1")
    instruction = str(messages[-1].content)

    assert "Round 2" in instruction
    assert "revision" in instruction.lower()
    assert "shared condition -> proposed alternative" in instruction

    # 過去手はすべて履歴メッセージに内包される（指示文には生データを再掲しない）。
    rendered = "\n".join(str(m.content) for m in messages if isinstance(m, AIMessage))
    assert "first main conclusion" in rendered
    assert "second main conclusion" in rendered
    assert "previous counter conclusion" in rendered
    assert "first main conclusion" not in instruction


async def test_can_generate_main_finishes_when_no_new_main_argument(monkeypatch) -> None:
    async def no_new_argument(*args, **kwargs):
        return SimpleNamespace(
            can_generate="NO",
            reason="All available main arguments were already presented.",
        )

    monkeypatch.setattr("agent.nodes.invoke_agent_structured_messages", no_new_argument)

    state = State(
        question="What camera should we buy?",
        agent1_stance="a is a camera.",
        agent2_stance="",
    )
    update = await can_generate_main(state)

    assert update["main_argument_available"] is False
    assert (
        update["main_argument_unavailable_reason"]
        == "All available main arguments were already presented."
    )
    assert update["justification_status"] == "no_new_main_argument"
    assert (
        route_after_can_generate_main(SimpleNamespace(error=None, **update))
        == "finish"
    )


async def test_can_generate_main_routes_to_generation_when_available(monkeypatch) -> None:
    async def has_new_argument(*args, **kwargs):
        return SimpleNamespace(
            can_generate="YES",
            reason="A distinct main argument is available.",
            Argument=ArgumentBody(rules=[]),
        )

    monkeypatch.setattr("agent.nodes.invoke_agent_structured_messages", has_new_argument)

    state = State(
        question="What camera should we buy?",
        agent1_stance="a is a camera.",
        agent2_stance="",
    )
    update = await can_generate_main(state)

    assert update["main_argument_available"] is True
    assert update["main_argument_unavailable_reason"] is None
    assert update["current_argument"].argument
    assert update["current_argument"].round == state.debate_round
    assert update["history"][-1] is update["current_argument"]
    assert (
        route_after_can_generate_main(SimpleNamespace(error=None, finalize_mode=False, **update))
        == "o_defeat_a"
    )


async def test_can_generate_main_errors_when_yes_without_argument(monkeypatch) -> None:
    async def missing_argument(*args, **kwargs):
        return SimpleNamespace(
            can_generate="YES",
            reason="A distinct main argument is available.",
            Argument=None,
        )

    monkeypatch.setattr("agent.nodes.invoke_agent_structured_messages", missing_argument)

    state = State(
        question="What camera should we buy?",
        agent1_stance="c is a camera.",
        agent2_stance="",
    )
    update = await can_generate_main(state)

    assert update["error"] == "Main argument availability was YES but no Argument was generated."
    assert (
        route_after_can_generate_main(SimpleNamespace(**update))
        == "finish_with_error"
    )
