from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.graphs import nodes
from agent.graphs.defeat_workflow import DefeatSubgraphResult

pytestmark = pytest.mark.anyio


def argument(agent: str, conc: list[str], ass: list[str] | None = None, attack: str | None = None):
    payload = {"Argument": {"rules": [], "Conc": conc, "Ass": ass or []}}
    return nodes.record(agent, "defeat", json.dumps(payload), attack=attack)  # type: ignore[arg-type]


async def test_validate_b_exposes_generated_undercut_in_history_and_update(monkeypatch) -> None:
    main = argument("AG1", ["We should choose a"])
    rebut = argument("AG2", ["We should not choose a"], ["a is available"], attack="rebut")
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
    module_path = Path(__file__).parents[2] / "src" / "def.py"
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

    assert validation_payload["attack"] == "undercut"
    assert validation_payload["thread_status"] == "justified"
    assert finish_payload["dialogue_history"][-1]["attack"] == "undercut"
