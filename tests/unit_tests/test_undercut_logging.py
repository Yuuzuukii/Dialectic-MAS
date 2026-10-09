from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent import nodes
from agent.argumentation_model import AttackEvaluation
from agent.schema.state import ArgumentRecord, DialogueNode

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


async def test_validate_b_logs_when_the_target_already_undercuts_the_rebut(
    monkeypatch,
) -> None:
    main = argument("AG1", ["We should choose a"])
    rebut = argument(
        "AG2", ["We should not choose a"], ["a is available"], attack="rebut"
    )

    async def undercut_by_target(*args, **kwargs):
        return AttackEvaluation(
            defeats=False,
            attack="rebut",
            relations=[],
            target_undercuts="my argument already shows a is available",
        )

    monkeypatch.setattr(nodes, "evaluate_attack", undercut_by_target)
    root = DialogueNode(argument_id=main.id)
    state = SimpleNamespace(
        current_argument=main,
        pending_attacker_argument=rebut,
        current_proponent="AG1",
        current_opponent="AG2",
        history=[main, rebut],
        argument_records=[main, rebut],
        learned_findings=[],
        ag2_thread_status=None,
        defeat_relations=[],
        dialogue_nodes=[root],
        node_stack=[root.id],
        attempt_log=[],
        max_dialogue_turns=None,
    )

    update = await nodes.validate_opponent_move(state)

    # B は defeat にならない。判定は既存の論証同士の関係で行うので、新しい発話（undercut の
    # 論証）は履歴に追加されない。同じフレームで別の B' を試す。
    assert "argument_records" not in update
    assert "dialogue_history" not in update
    assert update["last_attack_defeated"] is False
    assert update["pending_attacker_argument"] is None
    assert update["attempt_log"][-1]["kind"] == "rebut_undercut_by_target"
    assert update["attempt_log"][-1]["reason"] == "my argument already shows a is available"
    updated_root = next(n for n in update["dialogue_nodes"] if n.id == root.id)
    assert updated_root.outcome == "open"
    assert updated_root.attack_attempts == 1


async def test_cli_payload_labels_undercut_and_keeps_it_in_finish_history() -> None:
    module_path = Path(__file__).parents[2] / "experiments" / "dialogue" / "common.py"
    spec = importlib.util.spec_from_file_location("dialogue_cli", module_path)
    assert spec is not None and spec.loader is not None
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    undercut = argument("AG1", ["a is not available"], attack="undercut")
    history = [undercut.to_dialogue_dict()]

    validation_payload = cli._node_payload(
        "validate_opponent_move",
        {"last_generated_argument": undercut},
    )
    status_payload = cli._node_payload(
        "resolve_tree_status", {"ag1_thread_status": "justified"}
    )
    finish_payload = cli._node_payload("finish", {"dialogue_history": history})

    assert validation_payload["metadata"]["attack"] == "undercut"
    assert status_payload["thread_status"] == "justified"
    assert finish_payload["dialogue_history"][-1]["attack"] == "undercut"
