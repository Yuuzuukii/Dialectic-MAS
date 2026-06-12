from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent import arguments, nodes
from agent.defeats import DefeatSubgraphResult
from agent.schema.llm_outputs import Antecedent, ArgumentBody, Rule, UndercutOutput
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


async def test_validate_b_exposes_generated_undercut_in_history_and_update(
    monkeypatch,
) -> None:
    main = argument("AG1", ["We should choose a"])
    rebut = argument(
        "AG2", ["We should not choose a"], ["a is available"], attack="rebut"
    )
    undercut = argument("AG1", ["a is not available"], attack="undercut")

    async def blocked_rebut(*args, **kwargs):
        return DefeatSubgraphResult(
            defeats=False,
            attack="rebut",
            relations=[],
            blocker=undercut,
        )

    monkeypatch.setattr(nodes, "run_defeat_subgraph", blocked_rebut)
    state = SimpleNamespace(
        current_argument=main,
        b_argument=rebut,
        current_proponent="AG1",
        current_opponent="AG2",
        history=[main, rebut],
        learned_findings=[],
        ag2_thread_status=None,
        defeat_relations=[],
    )

    update = await nodes.validate_b_defeats_a(state)

    assert update["last_generated_argument"] is undercut
    assert update["dialogue_history"][-1]["attack"] == "undercut"
    assert update["current_thread_status"] == "justified"


async def test_cli_payload_labels_undercut_and_keeps_it_in_finish_history() -> None:
    module_path = Path(__file__).parents[2] / "src" / "cli.py"
    spec = importlib.util.spec_from_file_location("dialogue_cli", module_path)
    assert spec is not None and spec.loader is not None
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    undercut = argument("AG1", ["a is not available"], attack="undercut")
    history = [undercut.to_dialogue_dict()]

    validation_payload = cli._node_payload(
        "validate_b_defeats_a",
        {
            "last_generated_argument": undercut,
            "current_thread_status": "justified",
        },
    )
    finish_payload = cli._node_payload("finish", {"dialogue_history": history})

    assert validation_payload["metadata"]["attack"] == "undercut"
    assert validation_payload["thread_status"] == "justified"
    assert finish_payload["dialogue_history"][-1]["attack"] == "undercut"


async def test_undercut_output_does_not_request_attack_metadata() -> None:
    assert "Attack" not in UndercutOutput.model_fields


async def test_generate_undercut_assigns_attack_metadata(monkeypatch) -> None:
    async def available_undercut(*args, **kwargs):
        return UndercutOutput(
            can_undercut="YES",
            Argument=ArgumentBody(
                rules=[
                    Rule(
                        antecedent=Antecedent(strong=["a is not available"]),
                        consequent="a is not available",
                    )
                ]
            ),
        )

    monkeypatch.setattr(
        arguments, "invoke_agent_structured_messages", available_undercut
    )
    target = argument("AG2", ["We should eat a"], ["a is available"], attack="rebut")
    state = SimpleNamespace(
        current_proponent="AG1",
        history=[],
        agent1_stance="a is not available.",
        agent2_stance="",
    )

    generated = await arguments.generate_undercut(state, "AG1", target)

    assert generated is not None
    assert generated.attack == "undercut"
    assert generated.target_id == target.id
    assert generated.target_field == "Ass"
    # 現実装は undercut の対象フィールド (Ass) までは設定するが、
    # 具体的な target_statement は設定しない（None のまま）。
    assert generated.target_statement is None
