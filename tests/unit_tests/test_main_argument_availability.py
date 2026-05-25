from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from agent.graphs.dialectic_workflow import State
from agent.graphs.edges import route_after_can_generate_main
from agent.graphs.nodes import can_generate_main
from agent.lib.prompt_build import build_main_argument_prompt
from agent.schema.outputs.llm import ArgumentBody
from agent.schema.state import ArgumentRecord

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


async def test_initial_main_prompt_does_not_include_previous_move_context() -> None:
    prior = ArgumentRecord(
        type="main",
        argument=argument_payload("previous conclusion"),
        support=[],
        agent="AG1",
    )
    state = State(
        question="What should we choose?",
        agent1_stance="",
        agent2_stance="",
        history=[prior],
    )

    prompt = build_main_argument_prompt(state, "AG1")

    assert prompt.startswith("Issue:\nWhat should we choose?")
    assert "ProponentPreviousMoves" not in prompt
    assert "Revision Context:" not in prompt
    assert "previous conclusion" not in prompt


async def test_revision_main_prompt_uses_previous_main_and_integrated_rules_only() -> None:
    prior_main = ArgumentRecord(
        type="main",
        argument=argument_payload("previous main conclusion"),
        support=[],
        agent="AG1",
    )
    prior_counter = ArgumentRecord(
        type="counter",
        argument=argument_payload("previous counter conclusion"),
        support=[],
        agent="AG1",
    )
    state = State(
        question="What should we choose?",
        agent1_stance="",
        agent2_stance="",
        history=[prior_main, prior_counter],
        integrated_rules=["shared condition -> proposed alternative"],
    )

    prompt = build_main_argument_prompt(state, "AG1")

    assert "Revision Context:" in prompt
    assert "previous main conclusion" in prompt
    assert "shared condition -> proposed alternative" in prompt
    assert "previous counter conclusion" not in prompt
    assert "ProponentPreviousMoves" not in prompt


async def test_can_generate_main_finishes_when_no_new_main_argument(monkeypatch) -> None:
    async def no_new_argument(*args, **kwargs):
        return SimpleNamespace(
            can_generate="NO",
            reason="All available main arguments were already presented.",
        )

    monkeypatch.setattr("agent.graphs.nodes.invoke_agent_structured", no_new_argument)

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

    monkeypatch.setattr("agent.graphs.nodes.invoke_agent_structured", has_new_argument)

    state = State(
        question="What camera should we buy?",
        agent1_stance="a is a camera.",
        agent2_stance="",
    )
    update = await can_generate_main(state)

    assert update["main_argument_available"] is True
    assert update["main_argument_unavailable_reason"] is None
    assert update["current_argument"].argument
    assert update["history"][-1] is update["current_argument"]
    assert (
        route_after_can_generate_main(SimpleNamespace(error=None, **update))
        == "o_defeat_a"
    )


async def test_can_generate_main_errors_when_yes_without_argument(monkeypatch) -> None:
    async def missing_argument(*args, **kwargs):
        return SimpleNamespace(
            can_generate="YES",
            reason="A distinct main argument is available.",
            Argument=None,
        )

    monkeypatch.setattr("agent.graphs.nodes.invoke_agent_structured", missing_argument)

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
