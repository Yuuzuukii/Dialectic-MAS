from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from agent import arguments
from agent.argumentation_model import evaluate_attack
from agent.arguments import argument_body_json
from agent.schema.llm_outputs import (
    Antecedent,
    ArgumentBody,
    AttackMetadata,
    DefeatingArgumentOutput,
    GeneralizedCriterion,
    Rule,
    TargetReference,
)
from agent.schema.state import ArgumentRecord

pytestmark = pytest.mark.anyio


def argument(
    agent: str, conc: list[str], ass: list[str] | None = None, attack: str | None = None
):
    payload = {
        "Argument": {
            "rules": [],
            "Conc": conc,
            "Ass": ass or [],
        }
    }
    return ArgumentRecord(
        type="defeat",
        argument=json.dumps(payload),
        support=[],
        agent=agent,  # type: ignore[arg-type]
        attack=attack,  # type: ignore[arg-type]
    )


async def test_rebut_defeats_when_target_side_cannot_undercut() -> None:
    async def no_undercut(*args, **kwargs):
        return None

    attacker = argument("AG2", ["We should not buy a"], attack="rebut")
    target = argument("AG1", ["We should buy a"])

    result = await evaluate_attack(
        SimpleNamespace(),
        attacker,
        target,
        "AG1",
        relation_context="test",
        blocker_generator=no_undercut,
    )

    assert result.defeats is True
    assert result.attack == "rebut"
    assert result.relations[-1].valid is True


async def test_rebut_does_not_defeat_when_target_side_undercuts() -> None:
    blocker = argument("AG1", ["attacker assumption is invalid"], attack="undercut")

    async def has_undercut(*args, **kwargs):
        return blocker

    attacker = argument(
        "AG2", ["We should not buy a"], ["no evidence of stock"], attack="rebut"
    )
    target = argument("AG1", ["We should buy a"])

    result = await evaluate_attack(
        SimpleNamespace(),
        attacker,
        target,
        "AG1",
        relation_context="test",
        blocker_generator=has_undercut,
    )

    assert result.defeats is False
    assert result.blocker is blocker
    assert result.relations[-1].attacker_id == blocker.id


async def test_undercut_defeats_when_valid() -> None:
    attacker = argument("AG2", ["a is not available"], attack="undercut")
    target = argument("AG1", ["We should buy a"], ["a is available"])

    result = await evaluate_attack(
        SimpleNamespace(),
        attacker,
        target,
        "AG1",
        relation_context="test",
    )

    assert result.defeats is True
    assert result.attack == "undercut"


async def test_declared_undercut_is_trusted_without_reverifying_assumption() -> None:
    # 現実装は LLM が宣言した攻撃メタデータを信用し、対象仮定との矛盾は再検証しない。
    # そのため、結論が対象仮定を否定していなくても undercut 宣言なら defeat が成立する。
    attacker = argument("AG2", ["b is expensive"], attack="undercut")
    target = argument("AG1", ["We should buy a"], ["a is available"])

    result = await evaluate_attack(
        SimpleNamespace(),
        attacker,
        target,
        "AG1",
        relation_context="test",
    )

    assert result.defeats is True
    assert result.attack == "undercut"
    assert result.relations[-1].valid is True


async def test_serialized_argument_payload_does_not_include_attack_metadata() -> None:
    payload = json.loads(argument_body_json(ArgumentBody(rules=[])))

    assert set(payload["Argument"]) == {"rules", "Conc", "Ass"}
    assert "attack" not in payload["Argument"]
    assert "target" not in payload["Argument"]


async def test_llm_argument_body_only_requests_rules() -> None:
    assert set(ArgumentBody.model_fields) == {"rules"}


async def test_llm_schema_does_not_request_generated_identifiers() -> None:
    assert "id" not in Rule.model_fields
    assert "id" not in GeneralizedCriterion.model_fields


async def test_defeating_output_requests_declared_attack_target() -> None:
    assert "Attack" in DefeatingArgumentOutput.model_fields
    assert set(AttackMetadata.model_fields) == {"method", "target"}
    assert set(TargetReference.model_fields) == {"field", "statement"}


async def test_generate_attack_infers_rebut_and_target_metadata(monkeypatch) -> None:
    async def available_rebut(*args, **kwargs):
        return DefeatingArgumentOutput(
            can_defeat="YES",
            Argument=ArgumentBody(
                rules=[
                    Rule(
                        antecedent=Antecedent(strong=["a exceeds the budget"]),
                        consequent="We should not buy a",
                    )
                ]
            ),
            Attack=AttackMetadata(
                method="rebut",
                target=TargetReference(field="Conc", statement="We should buy a"),
            ),
        )

    monkeypatch.setattr(arguments, "chat_structured", available_rebut)
    target = argument("AG1", ["We should buy a"])
    state = SimpleNamespace(
        current_proponent="AG1",
        history=[],
        agent1_stance="",
        agent2_stance="a exceeds the budget.",
    )

    generated = await arguments.generate_attack(
        state, "AG2", target, purpose="defeat"
    )

    assert generated is not None
    assert generated.attack == "rebut"
    assert generated.target_id == target.id
    assert generated.target_field == "Conc"
    assert generated.target_statement == "We should buy a"


async def test_generate_attack_trusts_declared_attack_target(monkeypatch) -> None:
    async def invalid_target(*args, **kwargs):
        return DefeatingArgumentOutput(
            can_defeat="YES",
            Argument=ArgumentBody(
                rules=[
                    Rule(
                        antecedent=Antecedent(strong=["a exceeds the budget"]),
                        consequent="We should not buy a",
                    )
                ]
            ),
            Attack=AttackMetadata(
                method="undercut",
                target=TargetReference(field="Ass", statement="a is available"),
            ),
        )

    monkeypatch.setattr(arguments, "chat_structured", invalid_target)
    target = argument("AG1", ["We should buy a"], ["a is available"])
    state = SimpleNamespace(
        current_proponent="AG1",
        history=[],
        agent1_stance="",
        agent2_stance="a exceeds the budget.",
    )

    generated = await arguments.generate_attack(
        state, "AG2", target, purpose="defeat"
    )

    # 現実装は宣言された攻撃対象を検証せず、そのまま採用して攻撃論証を生成する。
    assert generated is not None
    assert generated.attack == "undercut"
    assert generated.target_field == "Ass"
    assert generated.target_statement == "a is available"


async def test_declared_rebut_keeps_method_and_defeats() -> None:
    # rebut は undercut に再分類されず、宣言どおり rebut として defeat が成立する。
    attacker = argument("AG2", ["a is not available"], attack="rebut")
    attacker.target_field = "Ass"
    attacker.target_statement = "a is available"
    target = argument("AG1", ["We should buy a"], ["a is available"])

    result = await evaluate_attack(
        SimpleNamespace(),
        attacker,
        target,
        "AG1",
        relation_context="test",
    )

    assert result.defeats is True
    assert result.attack == "rebut"


async def test_serialized_argument_payload_derives_conc_and_ass_from_rules() -> None:
    payload = json.loads(
        argument_body_json(
            ArgumentBody(
                rules=[
                    Rule(
                        antecedent=Antecedent(
                            strong=["a is compact"],
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
