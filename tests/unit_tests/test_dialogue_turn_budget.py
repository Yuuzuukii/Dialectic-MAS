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
from agent.nodes import (
    _dialogue_turn_budget_exceeded,
    can_generate_main,
    opponent_move,
    proponent_move,
    validate_opponent_move,
)
from agent.schema.state import ArgumentRecord, DialogueNode
from agent.workflow import State

pytestmark = pytest.mark.anyio


def _main_record(agent: str = "AG1") -> ArgumentRecord:
    return ArgumentRecord(
        type="main",
        argument='{"Argument": {"rules": [], "Conc": ["c"], "Ass": []}}',
        support=[],
        agent=agent,  # type: ignore[arg-type]
        proponent=agent,  # type: ignore[arg-type]
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


def _find(nodes: list[DialogueNode], node_id: str) -> DialogueNode:
    return next(node for node in nodes if node.id == node_id)


async def test_opponent_move_treats_dialogue_budget_as_undetermined() -> None:
    """絶対ターン数上限（max_dialogue_turns）は「この論証が守り切れたか」とは無関係な
    実験全体のリソース都合の打ち切りなので、justified に倒す won_by_p ではなく、
    max_tree_depth 到達と同じ undetermined（→ resolve_tree_status で defensible）にする。"""
    main = _main_record("AG1")
    root = DialogueNode(argument_id=main.id)
    state = State(
        question="Q?",
        agent1_stance="s1",
        agent2_stance="s2",
        max_dialogue_turns=1,
        current_argument=main,
        current_proponent="AG1",
        current_opponent="AG2",
        argument_records=[main],
        dialogue_nodes=[root],
        node_stack=[root.id],
    )
    update = await opponent_move(state)

    updated = _find(update["dialogue_nodes"], root.id)
    assert updated.outcome == "undetermined"
    assert update["pending_attacker_argument"] is None




async def test_proponent_move_treats_dialogue_budget_as_undetermined() -> None:
    """max_dialogue_turns 到達は opponent_move 側と同様 undetermined として扱う
    （lost_by_p ではない。どちらも resolve_tree_status では defensible に落ちるが、
    outcome の意味としては「負けた」ではなく「わからない」が正しい）。"""
    main = _main_record("AG1")
    b_argument = ArgumentRecord(
        type="defeat",
        argument='{"Argument": {"rules": [], "Conc": ["not c"], "Ass": []}}',
        support=[],
        agent="AG2",  # type: ignore[arg-type]
        proponent="AG1",  # type: ignore[arg-type]
        attack="rebut",  # type: ignore[arg-type]
        target_id=main.id,
        target_field="Conc",
    )
    root = DialogueNode(argument_id=main.id, current_attacker_id=b_argument.id)
    state = State(
        question="Q?",
        agent1_stance="s1",
        agent2_stance="s2",
        max_dialogue_turns=2,
        current_argument=main,
        current_proponent="AG1",
        current_opponent="AG2",
        argument_records=[main, b_argument],
        dialogue_nodes=[root],
        node_stack=[root.id],
    )
    update = await proponent_move(state)

    updated = _find(update["dialogue_nodes"], root.id)
    assert updated.outcome == "undetermined"
    assert update["pending_counter_argument"] is None


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
    assert fd_route_after_ag1_turn(state) == "integrate"


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
    assert fd_route_after_ag2_turn(state) == "integrate"


def test_mad_route_after_ag2_turn_uses_integrate_when_synthesis_enabled() -> None:
    state = MADState(
        question="Q?",
        agent1_stance="s1",
        agent2_stance="s2",
        max_turns=1,
        round=2,
        use_synthesis=True,
        dialogue_history=[
            {"agent": "AG1", "round": 1, "argument": "x", "has_new_point": True},
            {"agent": "AG2", "round": 1, "argument": "y", "has_new_point": True},
        ],
        ag1_has_new=True,
        ag2_has_new=True,
    )
    assert mad_route_after_ag2_turn(state) == "integrate"


async def test_validate_opponent_move_disables_blocker_generation_once_budget_exceeded(
    monkeypatch,
) -> None:
    """undercut の"blocker"生成は`evaluate_attack`内部から呼ばれ、opponent_move等の
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
        proponent="AG1",  # type: ignore[arg-type]
        attack="rebut",  # type: ignore[arg-type]
        target_id=main.id,
        target_field="Conc",
    )
    root = DialogueNode(argument_id=main.id)
    state = State(
        question="Q?",
        agent1_stance="s1",
        agent2_stance="s2",
        max_dialogue_turns=2,
        current_argument=main,
        current_proponent="AG1",
        pending_attacker_argument=b_argument,
        argument_records=[main, b_argument],
        dialogue_nodes=[root],
        node_stack=[root.id],
    )
    await validate_opponent_move(state)

    assert captured["blocker_generator"] is None


def _defeat_record(agent: str, proponent: str) -> ArgumentRecord:
    return ArgumentRecord(
        type="defeat",
        argument='{"Argument": {"rules": [], "Conc": ["x"], "Ass": []}}',
        support=[],
        agent=agent,  # type: ignore[arg-type]
        proponent=proponent,  # type: ignore[arg-type]
    )


async def test_dialogue_turn_budget_splits_evenly_between_proponents() -> None:
    """max_dialogue_turns=10 は AG1/AG2 それぞれ5ずつに折半される。

    AG1 側の攻防がどれだけ長引いて自分の割り当て(5)を使い切っても、AG2 側の
    残り予算には影響しない。ユーザーが指摘した「AG1が長引くとAG2が今ラウンド
    一度も発言できない」問題への対処（schema のみ。MAD/Free Debate は厳密な
    交互発言で自然に均等になるため対象外）。
    """
    main = _main_record("AG1")
    ag1_records = [main] + [_defeat_record("AG2", "AG1") for _ in range(3)]

    state_ag1_used_4 = State(
        question="Q?",
        agent1_stance="s1",
        agent2_stance="s2",
        max_dialogue_turns=10,
        current_proponent="AG1",
        argument_records=ag1_records,  # main + 3 = AG1 が4消費
    )
    assert _dialogue_turn_budget_exceeded(state_ag1_used_4) is False  # 4 < 5

    state_ag1_used_5 = State(
        question="Q?",
        agent1_stance="s1",
        agent2_stance="s2",
        max_dialogue_turns=10,
        current_proponent="AG1",
        argument_records=[*ag1_records, _defeat_record("AG1", "AG1")],  # 5消費
    )
    assert _dialogue_turn_budget_exceeded(state_ag1_used_5) is True  # 5 >= 5

    # AG1 が自分の割り当て(5)を使い切っていても、AG2 はまだ0消費なので自分の
    # 割り当て分は丸ごと使える。
    state_ag2_fresh = State(
        question="Q?",
        agent1_stance="s1",
        agent2_stance="s2",
        max_dialogue_turns=10,
        current_proponent="AG2",
        argument_records=[*ag1_records, _defeat_record("AG1", "AG1")],
    )
    assert _dialogue_turn_budget_exceeded(state_ag2_fresh) is False


async def test_dialogue_turn_budget_odd_remainder_goes_to_ag1() -> None:
    """max_dialogue_turns=11 は AG1=6 / AG2=5 に割れる（端数は先手のAG1へ）."""
    main = _main_record("AG1")

    state_ag1_used_5 = State(
        question="Q?",
        agent1_stance="s1",
        agent2_stance="s2",
        max_dialogue_turns=11,
        current_proponent="AG1",
        argument_records=[main, *[_defeat_record("AG2", "AG1") for _ in range(4)]],
    )
    assert _dialogue_turn_budget_exceeded(state_ag1_used_5) is False  # 5 < 6

    state_ag2_used_5 = State(
        question="Q?",
        agent1_stance="s1",
        agent2_stance="s2",
        max_dialogue_turns=11,
        current_proponent="AG2",
        argument_records=[
            main,
            *[_defeat_record("AG1", "AG2") for _ in range(5)],
        ],  # main は proponent=AG1 なので AG2 の消費には数えない
    )
    assert _dialogue_turn_budget_exceeded(state_ag2_used_5) is True  # 5 >= 5
