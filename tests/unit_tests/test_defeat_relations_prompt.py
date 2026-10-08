"""攻撃の手番に渡す、発言の連番と defeat 関係の block（schema / no_schema 共通）のテスト."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from src.agent.arguments import (
    build_attack_messages,
    defeat_relations_block,
    numbered_history,
)
from src.agent.schema.state import ArgumentRecord, DefeatRelation


def _rec(rid: str, agent: str, kind: str) -> ArgumentRecord:
    return ArgumentRecord(id=rid, type=kind, argument=f"text {rid}", agent=agent)  # type: ignore[arg-type]


def _rel(a: str, t: str, valid: bool) -> DefeatRelation:
    return DefeatRelation(attacker_id=a, target_id=t, attack="rebut", valid=valid)


def _state(mode: str) -> Any:
    records = [
        _rec("m0", "AG1", "main"),
        _rec("m1", "AG2", "main"),
        _rec("b", "AG1", "defeat"),
        _rec("c", "AG2", "counter"),
    ]
    history = [AIMessage(content=r.argument, name=r.agent) for r in records]
    relations = [
        _rel("m1", "m0", True),  # 別スレッド（現在の main より前）。出さない
        _rel("b", "m1", True),
        _rel("c", "b", True),
        _rel("b", "c", True),
        _rel("b", "m1", False),
    ]
    return SimpleNamespace(
        output_mode=mode,
        agent1_stance="s1",
        agent2_stance="s2",
        question="q",
        debate_round=1,
        history=history,
        argument_records=records,
        current_argument=records[1],
        defeat_relations=relations,
    )


def test_block_lists_only_current_thread_with_mutual_marks() -> None:
    block = defeat_relations_block(_state("schema"))
    assert "[3] defeats [2]" in block
    assert "[4] defeats [3] (mutual: [3] also defeats [4])" in block
    assert "[2] defeats [1]" not in block
    # 成立した defeat がある組は、失敗の行を重ねない
    assert "does not defeat" not in block


def test_block_reports_failed_attack_and_empty_thread() -> None:
    state = _state("no_schema")
    state.defeat_relations = [_rel("b", "m1", False)]
    assert "[3] does not defeat [2]" in defeat_relations_block(state)
    state.defeat_relations = []
    assert "(none yet)" in defeat_relations_block(state)


@pytest.mark.parametrize("mode", ["schema", "no_schema"])
def test_history_is_numbered_and_instruction_carries_block(mode: str) -> None:
    state = _state(mode)
    assert str(numbered_history(state)[0].content).startswith("[1] ")
    messages = asyncio.run(
        build_attack_messages(
            state, "AG1", state.argument_records[3], purpose="counter"
        )
    )
    human = messages[-1]
    assert isinstance(human, HumanMessage)
    text = str(human.content)
    assert "<defeat_relations>" in text and "<target_number>[4]</target_number>" in text
    assert "Take them into account" in text


def test_numbering_skipped_when_counts_mismatch() -> None:
    state = _state("schema")
    state.history = state.history[:2]
    assert not str(numbered_history(state)[0].content).startswith("[1]")
