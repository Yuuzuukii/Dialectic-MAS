"""攻撃の成立判定（evaluate_attack）と、攻撃・論証の生成の単体テスト.

成立の判定は、議論を書く側とは別の LLM（attack_judge）が行う。ここでは、その判定をモックして、
Prakken & Sartor の defeat の定義（rebut は、対象のすでにある論証が undercut していないときだけ defeat）と、
対象を番号で選ぶ生成（番号から文を復元し、範囲外なら書き直させる）を確かめる。
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from agent import argumentation_model, arguments
from agent.argumentation_model import evaluate_attack
from agent.arguments import argument_body_json, resolve_draft
from agent.attack_judge import RebutVerdict, UndercutVerdict
from agent.schema.llm_outputs import (
    Antecedent,
    AntecedentDraft,
    ArgumentBody,
    ArgumentDraft,
    AttackMetadata,
    AttackMetadataFree,
    DefeatingArgumentOutput,
    DefeatingArgumentOutputFree,
    IntegrationBody,
    Rule,
    RuleDraft,
    TargetQuote,
    TargetReference,
)
from agent.schema.state import ArgumentRecord

pytestmark = pytest.mark.anyio


def argument(
    agent: str, conc: list[str], ass: list[str] | None = None, attack: str | None = None
):
    payload = {"Argument": {"rules": [], "Conc": conc, "Ass": ass or []}}
    return ArgumentRecord(
        type="defeat",
        argument=json.dumps(payload),
        support=[],
        agent=agent,  # type: ignore[arg-type]
        attack=attack,  # type: ignore[arg-type]
    )


def _state(mode: str = "schema") -> SimpleNamespace:
    return SimpleNamespace(
        question="Q?",
        output_mode=mode,
        current_proponent="AG1",
        history=[],
        agent1_stance="",
        agent2_stance="a exceeds the budget.",
        argument_records=[],
    )


def _judges(monkeypatch, *, rebut: bool = True, undercut: bool = True) -> dict[str, Any]:
    """judge_rebut / judge_undercut を差し替え、渡された引数を記録する."""
    seen: dict[str, Any] = {}

    async def fake_rebut(state, attack, statement, target=None):
        seen["rebut"] = statement
        return RebutVerdict(rebut, "judged")

    async def fake_undercut(state, attack, target, assumptions, **kwargs):
        seen["undercut"] = (assumptions, kwargs)
        return UndercutVerdict(undercut, assumptions[0] if undercut else None, "judged")

    monkeypatch.setattr(argumentation_model, "judge_rebut", fake_rebut)
    monkeypatch.setattr(argumentation_model, "judge_undercut", fake_undercut)
    return seen


async def test_rebut_defeats_when_judged_and_target_side_does_not_undercut(monkeypatch) -> None:
    seen = _judges(monkeypatch)

    async def not_undercut(own, attack):
        return None

    attacker = argument("AG2", ["We should not buy a"], attack="rebut")
    attacker.target_statement = "We should buy a"
    target = argument("AG1", ["We should buy a"])

    result = await evaluate_attack(
        _state(), attacker, target, "AG1", relation_context="test", undercut_check=not_undercut
    )

    assert result.defeats is True
    assert result.attack == "rebut"
    assert result.target_undercuts is None
    assert result.relations[-1].valid is True
    assert seen["rebut"] == "We should buy a"


async def test_rebut_not_established_by_the_judge_does_not_defeat(monkeypatch) -> None:
    _judges(monkeypatch, rebut=False)

    async def never_called(own, attack):
        raise AssertionError("the existing-undercut check is only for an established rebut")

    attacker = argument("AG2", ["b is cheaper"], attack="rebut")
    attacker.target_statement = "We should buy a"
    target = argument("AG1", ["We should buy a"])

    result = await evaluate_attack(
        _state(), attacker, target, "AG1", relation_context="test", undercut_check=never_called
    )

    assert result.defeats is False
    assert result.target_undercuts is None
    assert "rebut not established" in result.relations[-1].reason


async def test_rebut_does_not_defeat_when_target_already_undercuts_it(monkeypatch) -> None:
    _judges(monkeypatch)
    seen: list[tuple[str, str]] = []

    async def already_undercuts(own, attack):
        seen.append((own.id, attack.id))
        return "my argument already shows the stock exists"

    attacker = argument(
        "AG2", ["We should not buy a"], ["no evidence of stock"], attack="rebut"
    )
    attacker.target_statement = "We should buy a"
    target = argument("AG1", ["We should buy a"])

    result = await evaluate_attack(
        _state(),
        attacker,
        target,
        "AG1",
        relation_context="test",
        undercut_check=already_undercuts,
    )

    # 判定されるのは、すでにある対象側の論証（own）と攻撃（attack）の組。新しい論証は作らない。
    assert seen == [(target.id, attacker.id)]
    assert result.defeats is False
    assert result.target_undercuts == "my argument already shows the stock exists"
    assert result.relations[-1].attacker_id == target.id
    assert result.relations[-1].target_id == attacker.id
    assert result.relations[-1].attack == "undercut"
    assert result.relations[-1].valid is True


async def test_undercut_attack_is_not_checked_for_target_side_undercut(monkeypatch) -> None:
    _judges(monkeypatch)

    async def never_called(own, attack):
        raise AssertionError("an established undercut defeats without any further check")

    attacker = argument("AG2", ["a is not available"], attack="undercut")
    attacker.target_statement = "a is available"
    target = argument("AG1", ["We should buy a"], ["a is available"])

    result = await evaluate_attack(
        _state(), attacker, target, "AG1", relation_context="test", undercut_check=never_called
    )

    assert result.defeats is True
    assert result.attack == "undercut"


async def test_undercut_is_judged_against_the_declared_assumption_only(monkeypatch) -> None:
    seen = _judges(monkeypatch)
    attacker = argument("AG2", ["a is not available"], attack="undercut")
    attacker.target_statement = "a is available"
    target = argument("AG1", ["We should buy a"], ["a is available", "b is cheap"])

    await evaluate_attack(_state(), attacker, target, "AG1", relation_context="test")

    assert seen["undercut"][0] == ["a is available"]
    assert seen["undercut"][1] == {"presumption_check": False}


async def test_no_schema_undercut_asks_the_judge_to_check_the_presumption(monkeypatch) -> None:
    seen = _judges(monkeypatch)
    target = ArgumentRecord(
        type="main",
        argument="We should buy a. This assumes a stays in stock.",
        support=[],
        agent="AG1",
    )
    attacker = ArgumentRecord(
        type="defeat",
        argument="a is being discontinued.",
        support=[],
        agent="AG2",
        attack="undercut",
        target_statement="This assumes a stays in stock.",
    )

    result = await evaluate_attack(
        _state("no_schema"), attacker, target, "AG1", relation_context="test"
    )

    assert result.defeats is True
    assert seen["undercut"][1] == {"presumption_check": True}


async def test_undercut_not_established_by_the_judge_does_not_defeat(monkeypatch) -> None:
    _judges(monkeypatch, undercut=False)
    attacker = argument("AG2", ["b is expensive"], attack="undercut")
    attacker.target_statement = "a is available"
    target = argument("AG1", ["We should buy a"], ["a is available"])

    result = await evaluate_attack(_state(), attacker, target, "AG1", relation_context="test")

    assert result.defeats is False
    assert result.relations[-1].valid is False
    assert "undercut not established" in result.relations[-1].reason


async def test_declared_target_that_is_not_in_the_target_does_not_defeat(monkeypatch) -> None:
    _judges(monkeypatch)
    attacker = argument("AG2", ["We should not buy a"], attack="rebut")
    attacker.target_statement = "a sentence the target never states"
    target = argument("AG1", ["We should buy a"])

    result = await evaluate_attack(_state(), attacker, target, "AG1", relation_context="test")

    assert result.defeats is False
    assert "not present in target" in result.relations[-1].reason


async def test_serialized_argument_payload_does_not_include_attack_metadata() -> None:
    payload = json.loads(argument_body_json(ArgumentBody(rules=[])))

    assert set(payload["Argument"]) == {"rules", "Conc", "Ass"}
    assert "attack" not in payload["Argument"]
    assert "target" not in payload["Argument"]


async def test_llm_argument_body_only_requests_rules() -> None:
    assert set(ArgumentBody.model_fields) == {"rules"}
    assert set(ArgumentDraft.model_fields) == {"rules"}


async def test_llm_draft_names_premises_by_rule_number_and_never_writes_them() -> None:
    assert set(AntecedentDraft.model_fields) == {"from_rules", "weak_negation"}
    assert set(Antecedent.model_fields) == {"strong", "from_rules", "weak_negation"}


async def test_llm_schema_does_not_request_generated_identifiers() -> None:
    assert "id" not in Rule.model_fields
    assert "id" not in IntegrationBody.model_fields


async def test_defeating_output_requests_the_target_by_number() -> None:
    assert "Attack" in DefeatingArgumentOutput.model_fields
    assert set(AttackMetadata.model_fields) == {"method", "target"}
    assert set(TargetReference.model_fields) == {"number"}


def _draft(consequent: str = "We should not buy a") -> ArgumentDraft:
    return ArgumentDraft(
        rules=[RuleDraft(antecedent=AntecedentDraft(), consequent=consequent)]
    )


def _output(method: str, number: int, consequent: str = "We should not buy a"):
    return DefeatingArgumentOutput(
        can_defeat="YES",
        Argument=_draft(consequent),
        Attack=AttackMetadata(method=method, target=TargetReference(number=number)),  # type: ignore[arg-type]
    )


def _sequence(monkeypatch, outputs: list[Any]) -> list[int]:
    """chat_structured が、outputs を順に返す。呼び出しの回数を記録する."""
    calls: list[int] = []
    iterator = iter(outputs)

    async def fake(messages, schema, **kwargs):
        calls.append(len(messages))
        return next(iterator)

    monkeypatch.setattr(arguments, "chat_structured", fake)
    return calls


async def test_generate_attack_restores_the_target_statement_from_the_number(monkeypatch) -> None:
    _sequence(monkeypatch, [_output("rebut", 2)])
    target = argument("AG1", ["We should buy a", "a is cheap"])

    generated = await arguments.generate_attack(_state(), "AG2", target, purpose="defeat")

    assert generated is not None
    assert generated.attack == "rebut"
    assert generated.target_id == target.id
    assert generated.target_field == "Conc"
    assert generated.target_statement == "a is cheap"  # 2 番目の結論（一字一句）


async def test_generate_attack_undercut_number_indexes_the_assumptions(monkeypatch) -> None:
    _sequence(monkeypatch, [_output("undercut", 2)])
    target = argument("AG1", ["We should buy a"], ["a is available", "a stays cheap"])

    generated = await arguments.generate_attack(_state(), "AG2", target, purpose="defeat")

    assert generated is not None
    assert generated.target_field == "Ass"
    assert generated.target_statement == "a stays cheap"


async def test_generate_attack_rewrites_when_the_number_is_out_of_range(monkeypatch) -> None:
    calls = _sequence(monkeypatch, [_output("rebut", 9), _output("rebut", 1)])
    target = argument("AG1", ["We should buy a"])

    generated = await arguments.generate_attack(_state(), "AG2", target, purpose="defeat")

    assert generated is not None
    assert generated.target_statement == "We should buy a"
    assert len(calls) == 2
    assert calls[1] == calls[0] + 1  # 書き直しの指示が、1 件、足されている


async def test_generate_attack_gives_up_after_the_allowed_rewrites(monkeypatch) -> None:
    calls = _sequence(monkeypatch, [_output("rebut", 9)] * 3)
    target = argument("AG1", ["We should buy a"])
    arguments.take_decline_reason()

    generated = await arguments.generate_attack(_state(), "AG2", target, purpose="defeat")

    assert generated is None
    assert len(calls) == 1 + arguments.MAX_REGENERATIONS
    reason = arguments.take_decline_reason()
    assert reason is not None and "well-formed attack" in reason


async def test_generate_attack_rejects_an_undercut_when_the_target_has_no_assumption(monkeypatch) -> None:
    _sequence(monkeypatch, [_output("undercut", 1)] * 3)
    target = argument("AG1", ["We should buy a"], [])

    assert (
        await arguments.generate_attack(_state(), "AG2", target, purpose="defeat") is None
    )


def _free_output(statement: str):
    return DefeatingArgumentOutputFree(
        can_defeat="YES",
        Argument="a is being discontinued.",
        Attack=AttackMetadataFree(method="undercut", target=TargetQuote(statement=statement)),
    )


_FREE_TARGET_TEXT = "We should buy a. This assumes a stays in stock."


def _free_target() -> ArgumentRecord:
    return ArgumentRecord(type="main", argument=_FREE_TARGET_TEXT, support=[], agent="AG1")


async def test_no_schema_attack_target_is_the_words_copied_from_the_target(monkeypatch) -> None:
    _sequence(monkeypatch, [_free_output("This assumes a stays in stock.")])

    generated = await arguments.generate_attack(
        _state("no_schema"), "AG2", _free_target(), purpose="defeat"
    )

    assert generated is not None
    assert generated.target_statement == "This assumes a stays in stock."
    assert generated.argument == "a is being discontinued."


async def test_no_schema_attack_rewrites_when_the_copied_words_are_not_in_the_target(monkeypatch) -> None:
    calls = _sequence(
        monkeypatch,
        [_free_output("It assumes the stock never runs out"), _free_output("assumes a stays in stock")],
    )

    generated = await arguments.generate_attack(
        _state("no_schema"), "AG2", _free_target(), purpose="defeat"
    )

    assert generated is not None
    assert generated.target_statement == "assumes a stays in stock"
    assert len(calls) == 2 and calls[1] == calls[0] + 1


async def test_no_schema_attack_gives_up_after_the_allowed_rewrites(monkeypatch) -> None:
    calls = _sequence(monkeypatch, [_free_output("a phrase the target never wrote")] * 3)
    arguments.take_decline_reason()

    generated = await arguments.generate_attack(
        _state("no_schema"), "AG2", _free_target(), purpose="defeat"
    )

    assert generated is None
    assert len(calls) == 1 + arguments.MAX_REGENERATIONS
    reason = arguments.take_decline_reason()
    assert reason is not None and "copied word for word" in reason


async def test_attack_instruction_lists_the_numbered_target_items() -> None:
    from agent.prompts import attack_instruction

    target = argument("AG1", ["We should buy a", "a is cheap"], ["a is available"])

    text = attack_instruction("defeat", target, state=_state())

    assert "<target_conclusions>\n[1] We should buy a\n[2] a is cheap\n</target_conclusions>" in text
    assert "<target_assumptions>\n[1] a is available\n</target_assumptions>" in text
    assert "never copy its text" in text


async def test_no_schema_attack_instruction_asks_to_copy_the_target_words() -> None:
    from agent.prompts import attack_instruction

    text = attack_instruction("defeat", _free_target(), state=_state("no_schema"))

    assert "<target_sentences>" not in text and "<target_conclusions>" not in text
    assert "word for word" in text
    assert "never copy its text" not in text


async def test_attack_instruction_task_does_not_frame_goal_as_defeating_the_target() -> None:
    from agent.prompts import attack_instruction

    target = argument("AG1", ["We should buy a"])

    defeat_text = attack_instruction("defeat", target)
    counter_text = attack_instruction("counter", target)

    for text in (defeat_text, counter_text):
        task_block = text.split("</task>")[0]
        assert "construct a defeating argument" not in task_block.lower()
        assert "defeats the target attack" not in task_block.lower()
        assert "<content_requirement>" in text


async def test_serialized_argument_payload_derives_conc_and_ass_from_rules() -> None:
    payload = json.loads(
        argument_body_json(
            ArgumentBody(
                rules=[
                    Rule(
                        antecedent=Antecedent(
                            strong=[],
                            weak_negation=["not unavailable(a)"],
                        ),
                        consequent="we should buy a",
                    )
                ]
            )
        )
    )

    assert payload["Argument"]["Conc"] == ["we should buy a"]
    assert payload["Argument"]["Ass"] == ["not unavailable(a)"]


async def test_resolved_argument_serializes_the_restored_strong_premises() -> None:
    draft = ArgumentDraft(
        rules=[
            RuleDraft(antecedent=AntecedentDraft(), consequent="a is compact"),
            RuleDraft(
                antecedent=AntecedentDraft(from_rules=[1]),
                consequent="we should buy a",
            ),
        ]
    )

    body, violations = resolve_draft(draft)
    payload = json.loads(argument_body_json(body))

    assert violations == []
    assert payload["Argument"]["rules"][1]["antecedent"]["strong"] == ["a is compact"]
    assert payload["Argument"]["Conc"] == ["a is compact", "we should buy a"]
