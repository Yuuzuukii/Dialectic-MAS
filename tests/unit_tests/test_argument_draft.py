"""論証の作り方（rules の形式）の単体テスト: 強い前提は前の規則の結論だけ、最初の規則は強い前提を持たない."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from agent import arguments
from agent.arguments import resolve_draft
from agent.prompts import PromptTemplates
from agent.schema.llm_outputs import (
    AntecedentDraft,
    ArgumentDraft,
    MainArgumentAvailabilityOutput,
    RuleDraft,
)

pytestmark = pytest.mark.anyio


def rule(consequent: str, *from_rules: int, weak: list[str] | None = None) -> RuleDraft:
    return RuleDraft(
        antecedent=AntecedentDraft(from_rules=list(from_rules), weak_negation=weak or []),
        consequent=consequent,
    )


def test_strong_premises_are_restored_from_the_cited_earlier_consequents() -> None:
    body, violations = resolve_draft(
        ArgumentDraft(
            rules=[rule("a is compact"), rule("a is cheap"), rule("we should buy a", 1, 2)]
        )
    )

    assert violations == []
    assert body.rules[2].antecedent.strong == ["a is compact", "a is cheap"]
    assert body.rules[2].antecedent.from_rules == [1, 2]


def test_any_earlier_rule_may_be_cited_not_only_the_previous_one() -> None:
    _, violations = resolve_draft(
        ArgumentDraft(rules=[rule("p"), rule("q", 1), rule("r", 1, 2)])
    )

    assert violations == []


def test_the_first_rule_has_no_strong_premise() -> None:
    _, violations = resolve_draft(ArgumentDraft(rules=[rule("p", 1)]))

    assert any("rule 1 cites rule 1" in v and "first rule has no premise" in v for v in violations)


def test_a_rule_cannot_cite_itself_or_a_later_rule() -> None:
    _, violations = resolve_draft(
        ArgumentDraft(rules=[rule("p"), rule("q", 2), rule("r", 3), rule("s", 1, 3, 4)])
    )

    assert any("rule 2 cites rule 2" in v for v in violations)
    assert any("rule 3 cites rule 3" in v for v in violations)
    assert any("rule 4 cites rule 4" in v for v in violations)


def test_a_later_rule_may_state_another_claim_without_a_premise() -> None:
    body, violations = resolve_draft(
        ArgumentDraft(rules=[rule("p"), rule("q"), rule("r", 1, 2)])
    )

    assert violations == []
    assert body.rules[1].antecedent.strong == []


def test_the_first_rule_may_carry_weak_negation_only() -> None:
    body, violations = resolve_draft(
        ArgumentDraft(rules=[rule("p", weak=["no evidence that p fails"]), rule("q", 1)])
    )

    assert violations == []
    assert body.rules[0].antecedent.weak_negation == ["no evidence that p fails"]


def test_two_rules_with_the_same_consequent_are_rejected() -> None:
    _, violations = resolve_draft(ArgumentDraft(rules=[rule("p"), rule("p"), rule("q", 1, 2)]))

    assert any("share the same consequent" in v for v in violations)


def test_a_non_final_consequent_must_be_cited_by_a_later_rule() -> None:
    _, violations = resolve_draft(ArgumentDraft(rules=[rule("p"), rule("q"), rule("r", 1)]))

    assert any("non-final consequent of rule 2 is never used" in v for v in violations)


def test_an_argument_without_rules_is_rejected() -> None:
    _, violations = resolve_draft(ArgumentDraft(rules=[]))

    assert violations == ["the Argument has no rule"]


def test_a_verdict_about_the_dialectical_game_is_rejected_as_a_conclusion() -> None:
    _, violations = resolve_draft(
        ArgumentDraft(rules=[rule("The privacy-based attack fails to defeat the claim.")])
    )

    assert any("verdict about the dialectical game" in v for v in violations)


def test_the_overlay_states_the_first_rule_and_premise_rules() -> None:
    system = PromptTemplates.ARGUMENT_SYSTEM

    assert "A strong premise is the consequent of an EARLIER rule" in system
    assert "A rule that cites no earlier rule has no strong premise." in system
    assert "Your stance, the dialogue history, and general knowledge cannot be cited as premises" in system
    assert "The FIRST rule has no strong premise" in system
    assert "never derive a consequent from an empty antecedent" not in system
    assert "FIRST rule's antecedent must already contain a strong premise" not in system


def _stub_main(monkeypatch, outputs: list[ArgumentDraft]) -> list[int]:
    calls: list[int] = []
    iterator = iter(outputs)

    async def fake(messages: list[Any], schema: Any, **kwargs: Any) -> Any:
        calls.append(len(messages))
        return MainArgumentAvailabilityOutput(
            can_generate="YES", reason="ok", Argument=next(iterator)
        )

    monkeypatch.setattr(arguments, "chat_structured", fake)
    return calls


def _state() -> SimpleNamespace:
    return SimpleNamespace(
        question="Q?",
        agent1_stance="s1",
        agent2_stance="s2",
        debate_round=1,
        integrated_rules=[],
        output_mode="schema",
        current_argument=None,
        current_proponent="AG1",
        ag1_revision_context=None,
        ag2_revision_context=None,
        history=[],
    )


async def test_generate_main_rewrites_a_malformed_argument_and_restores_premises(monkeypatch) -> None:
    calls = _stub_main(
        monkeypatch,
        [
            ArgumentDraft(rules=[rule("p", 1)]),  # 最初の規則が強い前提を持つ（違反）
            ArgumentDraft(rules=[rule("p"), rule("q", 1)]),
        ],
    )

    result = await arguments.generate_main(_state(), "AG1")

    assert result.available is True and result.argument is not None
    assert len(calls) == 2 and calls[1] == calls[0] + 1
    rules = json.loads(result.argument.argument)["Argument"]["rules"]
    assert rules[1]["antecedent"]["strong"] == ["p"]


async def test_generate_main_declines_when_it_stays_malformed(monkeypatch) -> None:
    calls = _stub_main(monkeypatch, [ArgumentDraft(rules=[rule("p", 1)])] * 3)

    result = await arguments.generate_main(_state(), "AG1")

    assert result.available is False and result.argument is None
    assert result.reason is not None and "well-formed Argument" in result.reason
    assert len(calls) == 1 + arguments.MAX_REGENERATIONS
