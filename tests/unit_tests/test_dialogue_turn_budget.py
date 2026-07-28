"""`max_dialogue_turns`（全手法共通の絶対ターン数上限）のテスト.

None（既定）なら既存の round/attempts ベースの挙動と完全に同じであること、
設定した場合は各手法の「新しいターンを生成する直前」の関門で正しく打ち切られる
ことを確認する。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent.free_debate import FreeDebateState
from agent.free_debate import route_after_ag1_turn as fd_route_after_ag1_turn
from agent.free_debate import route_after_ag2_turn as fd_route_after_ag2_turn
from agent.mad import MADState
from agent.mad import route_after_ag1_turn as mad_route_after_ag1_turn
from agent.mad import route_after_ag2_turn as mad_route_after_ag2_turn
from agent.nodes import can_generate_main, o_defeat_a, p_counter_b, validate_b_defeats_a
from agent.schema.state import ArgumentRecord
from agent.workflow import State

pytestmark = pytest.mark.anyio


def _main_record(agent: str = "AG1") -> ArgumentRecord:
    return ArgumentRecord(
        type="main",
        argument='{"Argument": {"rules": [], "Conc": ["c"], "Ass": []}}',
        support=[],
        agent=agent,  # type: ignore[arg-type]
    )


async def test_can_generate_main_stops_when_dialogue_turn_budget_reached(
    monkeypatch,
) -> None:
    async def should_not_be_called(*args, **kwargs):
        raise AssertionError("generate_main should not be called once the budget is hit")

    monkeypatch.setattr("agent.arguments.chat_structured", should_not_be_called)

    state = State(
        question="Q?",
        agent1_stance="s1",
        agent2_stance="s2",
        max_dialogue_turns=2,
        argument_records=[_main_record("AG1"), _main_record("AG2")],
    )
    update = await can_generate_main(state)

    assert update["main_argument_available"] is False
    assert update["justification_status"] == "no_new_main_argument"
    assert "max_dialogue_turns" in update["main_argument_unavailable_reason"]


async def test_can_generate_main_ignores_budget_when_unset(monkeypatch) -> None:
    async def has_new_argument(*args, **kwargs):
        from agent.schema.llm_outputs import ArgumentBody

        return SimpleNamespace(
            can_generate="YES",
            reason="ok",
            Argument=ArgumentBody(rules=[]),
        )

    monkeypatch.setattr("agent.arguments.chat_structured", has_new_argument)

    state = State(
        question="Q?",
        agent1_stance="s1",
        agent2_stance="s2",
        max_dialogue_turns=None,
        argument_records=[_main_record("AG1"), _main_record("AG2")],
    )
    update = await can_generate_main(state)

    assert update["main_argument_available"] is True


async def test_o_defeat_a_treats_budget_as_defensible_not_justified() -> None:
    main = _main_record("AG1")
    state = State(
        question="Q?",
        agent1_stance="s1",
        agent2_stance="s2",
        max_dialogue_turns=1,
        current_argument=main,
        current_proponent="AG1",
        current_opponent="AG2",
        argument_records=[main],
    )
    update = await o_defeat_a(state)

    assert update["current_thread_status"] == "defensible"


async def test_p_counter_b_treats_budget_as_defensible_not_overruled() -> None:
    main = _main_record("AG1")
    b_argument = ArgumentRecord(
        type="defeat",
        argument='{"Argument": {"rules": [], "Conc": ["not c"], "Ass": []}}',
        support=[],
        agent="AG2",  # type: ignore[arg-type]
        attack="rebut",  # type: ignore[arg-type]
        target_id=main.id,
        target_field="Conc",
    )
    state = State(
        question="Q?",
        agent1_stance="s1",
        agent2_stance="s2",
        max_dialogue_turns=2,
        current_argument=main,
        current_proponent="AG1",
        current_opponent="AG2",
        b_argument=b_argument,
        argument_records=[main, b_argument],
    )
    update = await p_counter_b(state)

    assert update["current_thread_status"] == "defensible"


def test_mad_route_after_ag1_turn_cuts_off_mid_round_when_budget_set() -> None:
    state = MADState(
        question="Q?",
        agent1_stance="s1",
        agent2_stance="s2",
        max_dialogue_turns=1,
        dialogue_history=[{"agent": "AG1", "round": 1, "argument": "x", "has_new_point": True}],
    )
    assert mad_route_after_ag1_turn(state) == "judge"


def test_mad_route_after_ag1_turn_proceeds_normally_when_unset() -> None:
    state = MADState(
        question="Q?",
        agent1_stance="s1",
        agent2_stance="s2",
        max_dialogue_turns=None,
        dialogue_history=[{"agent": "AG1", "round": 1, "argument": "x", "has_new_point": True}],
    )
    assert mad_route_after_ag1_turn(state) == "ag2_turn"


def test_mad_route_after_ag2_turn_respects_budget_over_max_turns() -> None:
    state = MADState(
        question="Q?",
        agent1_stance="s1",
        agent2_stance="s2",
        max_turns=5,
        max_dialogue_turns=2,
        round=2,
        dialogue_history=[
            {"agent": "AG1", "round": 1, "argument": "x", "has_new_point": True},
            {"agent": "AG2", "round": 1, "argument": "y", "has_new_point": True},
        ],
        ag1_has_new=True,
        ag2_has_new=True,
    )
    assert mad_route_after_ag2_turn(state) == "judge"


def test_free_debate_route_after_ag1_turn_cuts_off_mid_round_when_budget_set() -> None:
    state = FreeDebateState(
        question="Q?",
        agent1_stance="s1",
        agent2_stance="s2",
        max_dialogue_turns=1,
        dialogue_history=[{"agent": "AG1", "round": 1, "argument": "x", "has_new_point": True}],
    )
    assert fd_route_after_ag1_turn(state) == "generate_final_answer"


def test_free_debate_route_after_ag2_turn_respects_budget_over_max_turns() -> None:
    state = FreeDebateState(
        question="Q?",
        agent1_stance="s1",
        agent2_stance="s2",
        max_turns=5,
        max_dialogue_turns=2,
        round=2,
        dialogue_history=[
            {"agent": "AG1", "round": 1, "argument": "x", "has_new_point": True},
            {"agent": "AG2", "round": 1, "argument": "y", "has_new_point": True},
        ],
        ag1_has_new=True,
        ag2_has_new=True,
    )
    assert fd_route_after_ag2_turn(state) == "generate_final_answer"


async def test_validate_b_defeats_a_disables_blocker_generation_once_budget_exceeded(
    monkeypatch,
) -> None:
    """undercut の"blocker"生成は`evaluate_attack`内部から呼ばれ、o_defeat_a等の
    ガードを経由しない。ここで別途止めないと、budget超過後も追加でturnが増えてしまう
    （実測で確認済み: max_dialogue_turns=6のはずが7ターンまで生成される事例があった）。
    """
    captured: dict[str, object] = {}

    async def fake_evaluate_attack(*args, **kwargs):
        captured["blocker_generator"] = kwargs.get("blocker_generator")
        from agent.argumentation_model import AttackEvaluation

        return AttackEvaluation(defeats=True, attack="rebut", relations=[], blocker=None)

    monkeypatch.setattr("agent.nodes.evaluate_attack", fake_evaluate_attack)

    main = _main_record("AG1")
    b_argument = ArgumentRecord(
        type="defeat",
        argument='{"Argument": {"rules": [], "Conc": ["not c"], "Ass": []}}',
        support=[],
        agent="AG2",  # type: ignore[arg-type]
        attack="rebut",  # type: ignore[arg-type]
        target_id=main.id,
        target_field="Conc",
    )
    state = State(
        question="Q?",
        agent1_stance="s1",
        agent2_stance="s2",
        max_dialogue_turns=2,
        current_argument=main,
        current_proponent="AG1",
        b_argument=b_argument,
        argument_records=[main, b_argument],
    )
    await validate_b_defeats_a(state)

    assert captured["blocker_generator"] is None
