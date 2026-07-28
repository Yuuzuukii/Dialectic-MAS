"""Constraint-preservation generation prompts remain aligned across stages."""

from types import SimpleNamespace
from typing import Any

import pytest

from agent import arguments
from agent.arguments import validate_argument_body
from agent.prompts import (
    PromptTemplates,
    generalization_instruction,
    integration_instruction,
    main_instruction,
)
from agent.schema.llm_outputs import (
    Antecedent,
    ArgumentBody,
    IntegrationBody,
    IntegrationBodyFree,
    Rule,
)

pytestmark = pytest.mark.anyio


def _state() -> SimpleNamespace:
    return SimpleNamespace(
        question="Should phones be banned?",
        agent1_stance="AG1 REQUIREMENT: reduce distraction; preserve the 62% result.",
        agent2_stance="AG2 REQUIREMENT: preserve emergency contact and digital citizenship.",
        integrated_rules=[],
        debate_round=1,
        current_proponent="AG1",
        ag1_revision_context=None,
        warrant_result='{"Argument1": {}, "Argument2": {}}',
        generalization_result='{"Argument": []}',
    )


def test_main_argument_selects_one_reason_and_saves_the_rest_for_later() -> None:
    """main argumentは1論点に絞り、残りは後続ラウンドのために温存する（詰め込み防止）.

    stance全体の網羅は最終回答（_FINAL_ANSWER_PRESERVATION）側の責務であり、
    main argument側で全部を出し切らせると、後続ラウンドで新しい実質論点が
    尽きて反復（constructivenessの減点対象）に陥りやすいため分離した。
    """
    instruction = main_instruction(_state())

    assert "<stance_coverage>" in instruction
    assert "every distinct substantive reason" in instruction
    assert "Do not front-load all of them into this single argument" in instruction
    assert "Select the single reason that most directly and decisively" in instruction
    assert "Leave your stance's other distinct reasons available for later" in instruction
    assert "number, threshold, exception, or named affected group" in instruction


def test_generalization_and_integration_receive_both_source_stances() -> None:
    state = _state()

    for instruction in (
        generalization_instruction(state),
        integration_instruction(state),
    ):
        assert "<source_stances>" in instruction
        assert state.agent1_stance in instruction
        assert state.agent2_stance in instruction


def test_integration_preserves_opposing_condition_to_outcome_mappings() -> None:
    system = PromptTemplates.INTEGRATION_SYSTEM

    assert "condition-to-conclusion mapping" in system
    assert "Use OR only" in system
    assert "criteria support opposing outcomes" in system
    assert "outcomes ambiguous" in system
    assert "adjudicate them symmetrically" in system
    assert "same evidential threshold" in system
    assert "automatic veto" in system
    assert "Do not invent a precautionary or caution presumption" in system

    structured_rule_description = str(
        IntegrationBody.model_fields["rule"].description
    )
    free_rule_description = str(
        IntegrationBodyFree.model_fields["rule"].description
    )
    for description in (structured_rule_description, free_rule_description):
        assert "condition-to-conclusion mapping" in description
        assert "Use OR only" in description


def test_both_final_answer_paths_require_stance_constraint_audit() -> None:
    for system in (
        PromptTemplates.FINAL_ANSWER_SYSTEM,
        PromptTemplates.FINAL_ANSWER_NO_CONSENSUS_SYSTEM,
    ):
        assert "<constraint_preservation>" in system
        assert "AG1 Stance and AG2 Stance" in system
        assert "Account for every identified item" in system
        assert "do not replace them" in system
        assert "Never output the labels 'AG1' or 'AG2'" in system
        assert "Apply any integrated rule silently" in system
        assert "Do not offer additional work" in system


async def test_justified_final_answer_receives_integrated_rules(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def fake_chat_text(messages: list[Any], **kwargs: Any) -> str:
        captured["messages"] = messages
        return "answer"

    monkeypatch.setattr(arguments, "chat_text", fake_chat_text)
    state = SimpleNamespace(
        justified_argument="justified",
        dialogue_history=[],
        integrated_rules=["Preserve emergency contact while limiting distraction."],
        consensus_reached=True,
        question="Should phones be banned?",
        agent1_stance="Reduce distraction.",
        agent2_stance="Preserve emergency contact.",
    )

    assert await arguments.generate_final_answer(state) == "answer"
    user_message = captured["messages"][-1].content
    assert "Shared integrated rules produced in earlier rounds" in user_message
    assert state.integrated_rules[0] in user_message


def test_argument_validation_rejects_empty_placeholder_rule() -> None:
    body = ArgumentBody(
        rules=[
            Rule(
                antecedent=Antecedent(
                    strong=[],
                    weak_negation=["No additional rule needed."],
                ),
                consequent=" ",
            )
        ]
    )

    violations = validate_argument_body(body)

    assert "rule 1 has an empty consequent" in violations
    assert (
        "rule 1 has no meaningful strong or weak_negation antecedent" in violations
    )
