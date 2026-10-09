"""strictly defeat の判定（validate_proponent_move）の単体テスト.

優先順位がないとき、rebut は対称（C が B を rebut するなら B も C を rebut する）なので、
Prakken & Sartor の定義（Def 2.16）から SD(C, B) = U(C, B) ∧ ¬U(B, C)（U は undercut）となる。
C が B を defeat したあと、残りの undercut を別の LLM の判定で確かめ、strictly defeat か相互 defeat かを決める。
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from agent import nodes
from agent.argumentation_model import AttackEvaluation
from agent.attack_judge import UndercutVerdict
from agent.schema.state import ArgumentRecord, DialogueNode
from agent.workflow import State

pytestmark = pytest.mark.anyio


def _record(agent: str, type_: str, conc: str, ass: list[str] | None = None) -> ArgumentRecord:
    payload = {"Argument": {"rules": [], "Conc": [conc], "Ass": ass or []}}
    return ArgumentRecord(
        type=type_,  # type: ignore[arg-type]
        argument=json.dumps(payload),
        support=[],
        agent=agent,  # type: ignore[arg-type]
    )


def _state(c_attack: str) -> tuple[State, ArgumentRecord, ArgumentRecord]:
    main = _record("AG1", "main", "we should choose a").model_copy(update={"proponent": "AG1"})
    b = _record("AG2", "defeat", "not a", ["no evidence that a fails"])
    c = _record("AG1", "counter", "a holds", ["no evidence that b holds"])
    c.attack = c_attack  # type: ignore[assignment]
    root = DialogueNode(argument_id=main.id, current_attacker_id=b.id)
    state = State(
        question="Q?",
        agent1_stance="s1",
        agent2_stance="s2",
        current_argument=main,
        current_proponent="AG1",
        current_opponent="AG2",
        argument_records=[main, b, c],
        dialogue_nodes=[root],
        node_stack=[root.id],
        pending_counter_argument=c,
    )
    return state, b, c


async def _validate(
    monkeypatch, state: State, *, defeats: bool, attack: str, undercut_holds: bool
) -> tuple[dict[str, Any], list[tuple[str, str]]]:
    seen: list[tuple[str, str]] = []

    async def fake_evaluate(_state, attacker, target, _defender, **kwargs):
        return AttackEvaluation(defeats=defeats, attack=attack, relations=[])  # type: ignore[arg-type]

    async def fake_undercut(_state, attack_record, target_record, context="relation"):
        seen.append((attack_record.agent, target_record.agent))
        return UndercutVerdict(undercut_holds, None, "judged")

    monkeypatch.setattr(nodes, "evaluate_attack", fake_evaluate)
    monkeypatch.setattr(nodes, "undercut_relation", fake_undercut)
    update = await nodes.validate_proponent_move(state)
    return update, seen


def _child(update: dict[str, Any], state: State) -> DialogueNode:
    return next(n for n in update["dialogue_nodes"] if n.id == update["node_stack"][-1])


async def test_undercut_counter_strictly_defeats_when_b_does_not_undercut_c(monkeypatch) -> None:
    state, b, c = _state("undercut")

    update, seen = await _validate(monkeypatch, state, defeats=True, attack="undercut", undercut_holds=False)

    assert seen == [("AG2", "AG1")]  # U(B, C) を確かめる（B が C を undercut するか）
    assert _child(update, state).entered_by_mutual_defeat is False
    assert "mutual_defeat" not in [e["kind"] for e in update.get("attempt_log", [])]


async def test_undercut_counter_is_mutual_when_b_also_undercuts_c(monkeypatch) -> None:
    state, b, c = _state("undercut")

    update, seen = await _validate(monkeypatch, state, defeats=True, attack="undercut", undercut_holds=True)

    assert seen == [("AG2", "AG1")]
    assert _child(update, state).entered_by_mutual_defeat is True
    assert "mutual_defeat" in [e["kind"] for e in update["attempt_log"]]


async def test_rebut_counter_strictly_defeats_only_when_c_undercuts_b(monkeypatch) -> None:
    state, b, c = _state("rebut")

    update, seen = await _validate(monkeypatch, state, defeats=True, attack="rebut", undercut_holds=True)

    assert seen == [("AG1", "AG2")]  # U(C, B) を確かめる（C が B を undercut するか）
    assert _child(update, state).entered_by_mutual_defeat is False


async def test_rebut_counter_without_undercut_is_mutual_because_rebut_is_symmetric(monkeypatch) -> None:
    state, b, c = _state("rebut")

    update, seen = await _validate(monkeypatch, state, defeats=True, attack="rebut", undercut_holds=False)

    assert seen == [("AG1", "AG2")]
    assert _child(update, state).entered_by_mutual_defeat is True
    assert "mutual_defeat" in [e["kind"] for e in update["attempt_log"]]


async def test_a_counter_that_does_not_defeat_never_reaches_the_undercut_check(monkeypatch) -> None:
    state, b, c = _state("rebut")

    update, seen = await _validate(monkeypatch, state, defeats=False, attack="rebut", undercut_holds=True)

    assert seen == []
    assert update["last_counter_strictly_defeated"] is False
    # 弾かれた C は、枠を閉じず、P が同じ B への別の反撃をやり直す。
    assert update["last_counter_rejected"] is True
    root = next(n for n in update["dialogue_nodes"] if n.id == state.node_stack[-1])
    assert root.outcome == "open" and root.counter_attempts == 1


async def test_the_defeat_relations_record_whether_b_defeats_c(monkeypatch) -> None:
    state, b, c = _state("undercut")

    strict, _ = await _validate(monkeypatch, state, defeats=True, attack="undercut", undercut_holds=False)
    mutual, _ = await _validate(monkeypatch, state, defeats=True, attack="undercut", undercut_holds=True)

    strict_rel = strict["defeat_relations"][-1]
    mutual_rel = mutual["defeat_relations"][-1]
    assert (strict_rel.attacker_id, strict_rel.target_id, strict_rel.valid) == (b.id, c.id, False)
    assert (mutual_rel.attacker_id, mutual_rel.target_id, mutual_rel.valid) == (b.id, c.id, True)
