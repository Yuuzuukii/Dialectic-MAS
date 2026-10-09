"""攻撃の成立判定（attack_judge）の単体テスト: プロンプトの形と、判定結果の扱い（LLM はモックする）."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from agent import arguments, attack_judge
from agent.attack_judge import (
    PresumptionList,
    RebutJudgement,
    UndercutJudgement,
    assumptions_for,
    judge_rebut,
    judge_undercut,
    rebut_prompt,
    undercut_prompt,
    undercut_relation,
)
from agent.schema.state import ArgumentRecord

pytestmark = pytest.mark.anyio


def _schema_record(conc: list[str], ass: list[str] | None = None) -> ArgumentRecord:
    payload = {"Argument": {"rules": [], "Conc": conc, "Ass": ass or []}}
    return ArgumentRecord(type="defeat", argument=json.dumps(payload), support=[], agent="AG2")


def _free_record(text: str, agent: str = "AG2") -> ArgumentRecord:
    return ArgumentRecord(type="defeat", argument=text, support=[], agent=agent)  # type: ignore[arg-type]


def _state(mode: str = "schema") -> SimpleNamespace:
    return SimpleNamespace(
        question="Should we buy a?",
        output_mode=mode,
        agent1_stance="SECRET STANCE ONE",
        agent2_stance="SECRET STANCE TWO",
    )


def _asked(monkeypatch, replies: list[Any]) -> list[dict[str, Any]]:
    """chat_structured を差し替え、replies を順に返す。呼び出しの内容を記録する."""
    calls: list[dict[str, Any]] = []
    iterator = iter(replies)

    async def fake(messages, schema, **kwargs):
        calls.append({"prompt": messages[0].content, "schema": schema, **kwargs})
        return next(iterator)

    monkeypatch.setattr(attack_judge, "chat_structured", fake)
    return calls


def test_rebut_prompt_defines_rebut_over_any_conclusion_and_hides_stances() -> None:
    prompt = rebut_prompt(
        _state(), _schema_record(["We should not buy a", "a is dear"]), "We should buy a"
    )

    assert "one of the attack's conclusions directly opposes S" in prompt
    assert "including an intermediate one" in prompt
    assert "A difference of degree or hedging does not prevent a rebut" in prompt
    assert "<target_statement>\nWe should buy a\n</target_statement>" in prompt
    assert "Conclusions:\n[1] We should not buy a\n[2] a is dear" in prompt
    assert "SECRET STANCE" not in prompt
    assert "defeat" not in prompt.lower().replace("defeating", "")  # 攻撃の種類・決着状態を見せない


def test_no_schema_attack_is_shown_as_plain_text_without_a_conclusion_list() -> None:
    prompt = rebut_prompt(_state("no_schema"), _free_record("a is dear, so skip it."), "We should buy a")

    assert "a is dear, so skip it." in prompt
    assert "Conclusions:" not in prompt


def test_undercut_prompt_lists_numbered_assumptions_and_defines_undercut() -> None:
    target = _schema_record(["We should buy a"], ["a stays in stock", "a stays cheap"])
    prompt = undercut_prompt(
        _state(),
        _schema_record(["a is being discontinued"]),
        target,
        target.assumptions,
        presumption_check=False,
    )

    assert "<assumptions>\n[1] a stays in stock\n[2] a stays cheap\n</assumptions>" in prompt
    assert "establishes that X does hold" in prompt
    assert "Judge only what the attack already says" in prompt
    assert "must be a presumption that the target's reasoning relies on by default" not in prompt


def test_the_presumption_rule_is_added_only_when_requested() -> None:
    target = _free_record("We should buy a. This assumes a stays in stock.", "AG1")
    prompt = undercut_prompt(
        _state("no_schema"),
        _free_record("a is being discontinued."),
        target,
        ["This assumes a stays in stock."],
        presumption_check=True,
    )

    assert "must be a presumption that the target's reasoning relies on by default" in prompt
    assert "not the target's conclusion and not a plain fact it states" in prompt


async def test_judge_uses_the_external_model_not_the_debaters(monkeypatch) -> None:
    calls = _asked(monkeypatch, [RebutJudgement(attack_conclusion_quote="x", rebuts=True, reason="r")])
    monkeypatch.delenv("JUDGE_MODEL", raising=False)
    monkeypatch.setenv("MODEL", "gpt-5.4-nano")

    await judge_rebut(_state(), _schema_record(["x"]), "S")

    assert calls[0]["model"] == "gpt-5.4-mini"
    assert calls[0]["schema"] is RebutJudgement

    monkeypatch.setenv("JUDGE_MODEL", "judge-x")
    calls = _asked(monkeypatch, [RebutJudgement(attack_conclusion_quote="x", rebuts=False, reason="r")])
    await judge_rebut(_state(), _schema_record(["x"]), "S")
    assert calls[0]["model"] == "judge-x"


async def test_judge_rebut_returns_the_verdict_and_reason(monkeypatch) -> None:
    _asked(monkeypatch, [RebutJudgement(attack_conclusion_quote="q", rebuts=True, reason="contradicts S")])

    verdict = await judge_rebut(_state(), _schema_record(["x"]), "S")

    assert verdict.holds is True and verdict.reason == "contradicts S"


async def test_judge_undercut_returns_the_numbered_assumption(monkeypatch) -> None:
    _asked(
        monkeypatch,
        [UndercutJudgement(undercut_assumption_number=2, attack_conclusion_quote="q", reason="r")],
    )
    target = _schema_record(["c"], ["a1", "a2"])

    verdict = await judge_undercut(_state(), _schema_record(["x"]), target, ["a1", "a2"])

    assert verdict.holds is True and verdict.assumption == "a2"


async def test_judge_undercut_with_null_or_out_of_range_number_does_not_hold(monkeypatch) -> None:
    _asked(
        monkeypatch,
        [
            UndercutJudgement(undercut_assumption_number=None, reason="none"),
            UndercutJudgement(undercut_assumption_number=5, reason="bad number"),
        ],
    )
    target = _schema_record(["c"], ["a1"])

    assert (await judge_undercut(_state(), _schema_record(["x"]), target, ["a1"])).holds is False
    assert (await judge_undercut(_state(), _schema_record(["x"]), target, ["a1"])).holds is False


async def test_judge_undercut_without_assumptions_does_not_call_the_llm(monkeypatch) -> None:
    calls = _asked(monkeypatch, [])

    verdict = await judge_undercut(_state(), _schema_record(["x"]), _schema_record(["c"]), [])

    assert verdict.holds is False and calls == []


async def test_schema_assumptions_are_the_ass_of_the_argument(monkeypatch) -> None:
    calls = _asked(monkeypatch, [])
    record = _schema_record(["c"], ["a1", "a2"])

    assert await assumptions_for(_state(), record) == ["a1", "a2"]
    assert calls == []


async def test_no_schema_assumptions_are_verbatim_presumptions_and_cached(monkeypatch) -> None:
    text = "We should buy a unless it is discontinued. Assuming there is no recall, it is safe."
    calls = _asked(
        monkeypatch,
        [
            PresumptionList(
                presumptions=[
                    "unless it is discontinued",
                    "Assuming there is no recall",
                    "a phrase the argument never wrote",
                ]
            )
        ],
    )
    record = _free_record(text, "AG1")

    first = await assumptions_for(_state("no_schema"), record)
    second = await assumptions_for(_state("no_schema"), record)

    assert first == ["unless it is discontinued", "Assuming there is no recall"]
    assert second == first
    assert len(calls) == 1  # 同じ論証は、一度しか取り出さない
    assert "Do not infer presumptions" in calls[0]["prompt"]


async def test_undercut_relation_without_any_assumption_does_not_call_the_llm(monkeypatch) -> None:
    calls = _asked(monkeypatch, [])

    verdict = await undercut_relation(_state(), _schema_record(["x"]), _schema_record(["c"], []))

    assert verdict.holds is False and calls == []


async def test_undercut_relation_judges_against_all_assumptions_of_the_target(monkeypatch) -> None:
    calls = _asked(
        monkeypatch,
        [UndercutJudgement(undercut_assumption_number=1, attack_conclusion_quote="q", reason="r")],
    )
    target = _schema_record(["c"], ["a1", "a2"])

    verdict = await undercut_relation(_state(), _schema_record(["x"]), target)

    assert verdict.holds is True and verdict.assumption == "a1"
    assert "[1] a1\n[2] a2" in calls[0]["prompt"]


async def test_ask_existing_undercut_returns_the_reason_only_when_it_holds(monkeypatch) -> None:
    _asked(
        monkeypatch,
        [
            UndercutJudgement(undercut_assumption_number=1, attack_conclusion_quote="q", reason="a is in fact available"),
            UndercutJudgement(undercut_assumption_number=None, reason="no"),
        ],
    )
    own = _schema_record(["a is available"])
    rebut = _schema_record(["We should not eat a"], ["a is not available"])
    state = _state()

    assert await arguments.ask_existing_undercut(state, "AG1", own, rebut) == "a is in fact available"
    assert await arguments.ask_existing_undercut(state, "AG1", own, rebut) is None


async def test_ask_existing_undercut_skips_the_llm_when_the_rebut_has_no_assumptions(monkeypatch) -> None:
    calls = _asked(monkeypatch, [])
    own = _schema_record(["We should eat a"])
    rebut = _schema_record(["We should not eat a"], [])

    assert await arguments.ask_existing_undercut(_state(), "AG1", own, rebut) is None
    assert calls == []
