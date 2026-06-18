from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from agent.arguments import build_main_argument_messages
from agent.edges import route_after_can_generate_main, route_after_thread
from agent.nodes import advance_to_ag2, can_generate_main
from agent.prompts import main_instruction
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
    assert "<protocol_flow>" not in system
    assert "<task>" not in system
    assert "<schema_overlay>" in system

    # 履歴は全フェーズで与える → 過去の主張が AIMessage として含まれる。
    history_msgs = [m for m in messages if isinstance(m, AIMessage)]
    assert len(history_msgs) == 1
    assert history_msgs[0].name == "AG1"
    assert "previous conclusion" in str(history_msgs[0].content)

    instruction = str(messages[-1].content)
    assert "Round 1" in instruction
    assert "<issue>\nWhat should we choose?\n</issue>" in instruction
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

    monkeypatch.setattr("agent.arguments.chat_structured", no_new_argument)

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
        route_after_can_generate_main(
            SimpleNamespace(error=None, current_proponent="AG1", **update)
        )
        == "advance_to_ag2"
    )


async def test_can_generate_main_routes_to_generation_when_available(monkeypatch) -> None:
    async def has_new_argument(*args, **kwargs):
        return SimpleNamespace(
            can_generate="YES",
            reason="A distinct main argument is available.",
            Argument=ArgumentBody(rules=[]),
        )

    monkeypatch.setattr("agent.arguments.chat_structured", has_new_argument)

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
    assert isinstance(update["history"][-2], HumanMessage)
    assert isinstance(update["history"][-1], AIMessage)
    assert update["history"][-1].name == "AG1"
    assert update["argument_records"][-1] is update["current_argument"]
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

    monkeypatch.setattr("agent.arguments.chat_structured", missing_argument)

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


async def test_can_generate_main_increments_main_attempt_count(monkeypatch) -> None:
    async def has_new_argument(*args, **kwargs):
        return SimpleNamespace(
            can_generate="YES",
            reason="A distinct main argument is available.",
            Argument=ArgumentBody(rules=[]),
        )

    monkeypatch.setattr("agent.arguments.chat_structured", has_new_argument)

    state = State(
        question="What camera should we buy?",
        agent1_stance="a is a camera.",
        agent2_stance="",
        main_attempt_count=1,
    )
    update = await can_generate_main(state)

    assert update["main_attempt_count"] == 2


async def test_route_after_can_generate_main_ag1_unavailable_advances_to_ag2() -> None:
    state = SimpleNamespace(
        error=None,
        current_proponent="AG1",
        main_argument_available=False,
        finalize_mode=False,
    )

    assert route_after_can_generate_main(state) == "advance_to_ag2"


async def test_route_after_can_generate_main_ag2_unavailable_extracts_warrants() -> None:
    state = SimpleNamespace(
        error=None,
        current_proponent="AG2",
        main_argument_available=False,
        finalize_mode=False,
    )

    assert route_after_can_generate_main(state) == "extract_warrants"


async def test_route_after_thread_retries_same_proponent_when_under_attempt_cap() -> None:
    state = SimpleNamespace(
        error=None,
        current_thread_status="overruled",
        current_proponent="AG1",
        main_attempt_count=1,
        max_main_argument_attempts=2,
    )

    assert route_after_thread(state) == "can_generate_main"


async def test_route_after_thread_advances_to_ag2_when_ag1_attempt_cap_reached() -> None:
    state = SimpleNamespace(
        error=None,
        current_thread_status="defensible",
        current_proponent="AG1",
        main_attempt_count=2,
        max_main_argument_attempts=2,
    )

    assert route_after_thread(state) == "advance_to_ag2"


async def test_route_after_thread_extracts_warrants_when_ag2_attempt_cap_reached() -> None:
    state = SimpleNamespace(
        error=None,
        current_thread_status="overruled",
        current_proponent="AG2",
        main_attempt_count=2,
        max_main_argument_attempts=2,
    )

    assert route_after_thread(state) == "extract_warrants"


async def test_advance_to_ag2_resets_state_for_ag2_turn() -> None:
    state = State(
        question="What camera should we buy?",
        agent1_stance="a is a camera.",
        agent2_stance="b is a camera.",
        main_attempt_count=2,
    )

    update = await advance_to_ag2(state)

    assert update["current_proponent"] == "AG2"
    assert update["current_opponent"] == "AG1"
    assert update["active_agent"] == "AG2"
    assert update["current_argument"] is None
    assert update["main_attempt_count"] == 0
    assert update["debate_stage"] == "ag2_main_thread"


async def test_main_instruction_shows_revision_context_without_integrated_rules() -> None:
    state = State(
        question="What should we choose?",
        agent1_stance="Your stance: choose A.",
        agent2_stance="",
        ag1_revision_context=(
            "AG1's previous main argument was overruled by AG2's defeat. "
            "Do not repeat the same main argument unless this defeating reason is resolved."
        ),
    )

    instruction = main_instruction(state)

    assert "<revision_context>" in instruction
    assert "AG1's previous main argument was overruled" in instruction
    assert "<integrated_rules>" not in instruction
    assert "Ground your NEW main argument in the integrated rules below." not in instruction
