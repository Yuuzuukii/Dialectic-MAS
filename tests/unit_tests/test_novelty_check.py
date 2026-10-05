"""反撃の非反復の自己点検（Novelty）の単体テスト."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from agent import arguments
from agent.prompts import attack_instruction
from agent.schema.llm_outputs import (
    Antecedent,
    ArgumentBody,
    AttackMetadata,
    DefeatingArgumentOutput,
    DefeatingArgumentOutputFree,
    NoveltyCheck,
    Rule,
    TargetReference,
)
from agent.schema.state import ArgumentRecord

pytestmark = pytest.mark.anyio


def _target() -> ArgumentRecord:
    payload = {"Argument": {"rules": [], "Conc": ["We should not buy a"], "Ass": []}}
    return ArgumentRecord(
        type="defeat",
        argument=json.dumps(payload),
        support=[],
        agent="AG2",
        attack="rebut",
    )


def _output(novelty: NoveltyCheck | None) -> DefeatingArgumentOutput:
    return DefeatingArgumentOutput(
        Novelty=novelty,
        can_defeat="YES",
        Argument=ArgumentBody(
            rules=[
                Rule(
                    antecedent=Antecedent(strong=["a is affordable"]),
                    consequent="We should buy a",
                )
            ]
        ),
        Attack=AttackMetadata(
            method="rebut",
            target=TargetReference(field="Conc", statement="We should not buy a"),
        ),
    )


def _state() -> SimpleNamespace:
    return SimpleNamespace(
        current_proponent="AG1",
        history=[],
        agent1_stance="a is affordable.",
        agent2_stance="",
        argument_records=[],
    )


async def _generate(monkeypatch: pytest.MonkeyPatch, output: DefeatingArgumentOutput, purpose: str):
    async def fake(*_args, **_kwargs):
        return output

    monkeypatch.setattr(arguments, "chat_structured", fake)
    arguments.take_decline_reason()
    generated = await arguments.generate_attack(_state(), "AG1", _target(), purpose=purpose)
    return generated, arguments.take_decline_reason()


async def test_counter_that_adds_no_new_reason_is_not_made(monkeypatch) -> None:
    novelty = NoveltyCheck(closest_earlier_id="arg-1", adds_new_reason="NO")

    generated, reason = await _generate(monkeypatch, _output(novelty), "counter")

    assert generated is None
    assert reason is not None and "Repeats a reason I already used" in reason
    assert "arg-1" in reason


async def test_counter_that_claims_a_new_reason_without_stating_it_is_not_made(monkeypatch) -> None:
    novelty = NoveltyCheck(closest_earlier_id="arg-1", adds_new_reason="YES", new_reason="  ")

    generated, _ = await _generate(monkeypatch, _output(novelty), "counter")

    assert generated is None


async def test_counter_with_a_new_reason_is_made(monkeypatch) -> None:
    novelty = NoveltyCheck(
        closest_earlier_id="arg-1", adds_new_reason="YES", new_reason="the price fell this year"
    )

    generated, reason = await _generate(monkeypatch, _output(novelty), "counter")

    assert generated is not None
    assert reason is None


async def test_counter_without_a_novelty_declaration_is_not_blocked(monkeypatch) -> None:
    generated, _ = await _generate(monkeypatch, _output(None), "counter")

    assert generated is not None


async def test_the_opponent_may_repeat_so_its_attack_is_not_checked(monkeypatch) -> None:
    novelty = NoveltyCheck(closest_earlier_id="arg-1", adds_new_reason="NO")

    generated, _ = await _generate(monkeypatch, _output(novelty), "defeat")

    assert generated is not None


def test_the_check_comes_first_in_both_output_schemas_and_in_the_counter_instruction() -> None:
    assert list(DefeatingArgumentOutput.model_fields)[0] == "Novelty"
    assert list(DefeatingArgumentOutputFree.model_fields)[0] == "Novelty"
    state = SimpleNamespace(question="Q?", debate_round=1)

    counter = attack_instruction("counter", _target(), state=state)
    defeat = attack_instruction("defeat", _target(), state=state)

    assert "Novelty" in counter
    assert "Novelty" not in defeat
