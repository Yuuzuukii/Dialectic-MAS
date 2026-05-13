from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from agent.graphs.defeat_workflow import run_defeat_subgraph, run_strict_defeat_subgraph
from agent.graphs.nodes import (
    argument_body_json,
    record,
)
from agent.schema.outputs.schema import ArgumentBody

pytestmark = pytest.mark.anyio


def argument(agent: str, conc: list[str], ass: list[str] | None = None, attack: str | None = None):
    payload = {
        "Argument": {
            "rules": [],
            "Conc": conc,
            "Ass": ass or [],
        }
    }
    return record(agent, "defeat", json.dumps(payload), attack=attack)  # type: ignore[arg-type]


async def test_rebut_defeats_when_target_side_cannot_undercut() -> None:
    async def no_undercut(*args, **kwargs):
        return None

    attacker = argument("AG2", ["We should not buy a"], attack="rebut")
    target = argument("AG1", ["We should buy a"])

    result = await run_defeat_subgraph(
        SimpleNamespace(),
        attacker,
        target,
        "AG1",
        relation_context="test",
        blocker_generator=no_undercut,
    )

    assert result.defeats is True
    assert result.attack == "rebut"
    assert result.relations[-1].valid is True


async def test_rebut_does_not_defeat_when_target_side_undercuts() -> None:
    blocker = argument("AG1", ["attacker assumption is invalid"], attack="undercut")

    async def has_undercut(*args, **kwargs):
        return blocker

    attacker = argument("AG2", ["We should not buy a"], ["no evidence of stock"], attack="rebut")
    target = argument("AG1", ["We should buy a"])

    result = await run_defeat_subgraph(
        SimpleNamespace(),
        attacker,
        target,
        "AG1",
        relation_context="test",
        blocker_generator=has_undercut,
    )

    assert result.defeats is False
    assert result.blocker is blocker
    assert result.relations[-1].attacker_id == blocker.id


async def test_undercut_defeats_when_valid() -> None:
    attacker = argument("AG2", ["stock evidence exists"], attack="undercut")
    target = argument("AG1", ["We should buy a"], ["no evidence of stock"])

    result = await run_defeat_subgraph(
        SimpleNamespace(),
        attacker,
        target,
        "AG1",
        relation_context="test",
    )

    assert result.defeats is True
    assert result.attack == "undercut"


async def test_strict_defeat_reuses_reverse_defeat_check() -> None:
    c = argument("AG1", ["stock evidence exists"], attack="undercut")
    b = argument("AG2", ["We should not buy a"], ["no evidence of stock"], attack="rebut")

    result = await run_strict_defeat_subgraph(
        SimpleNamespace(),
        c,
        b,
        forward_defender="AG2",
        reverse_defender="AG1",
    )

    assert result.strictly_defeats is True
    assert result.forward is not None and result.forward.defeats is True
    assert result.reverse is not None and result.reverse.defeats is False


async def test_strict_defeat_false_when_reverse_defeat_also_holds() -> None:
    async def no_undercut(*args, **kwargs):
        return None

    c = argument("AG1", ["We should buy a"], attack="rebut")
    b = argument("AG2", ["We should not buy a"], attack="rebut")

    result = await run_strict_defeat_subgraph(
        SimpleNamespace(),
        c,
        b,
        forward_defender="AG2",
        reverse_defender="AG1",
        blocker_generator=no_undercut,
    )

    assert result.strictly_defeats is False
    assert result.forward is not None and result.forward.defeats is True
    assert result.reverse is not None and result.reverse.defeats is True


async def test_serialized_argument_payload_does_not_include_attack_metadata() -> None:
    payload = json.loads(argument_body_json(ArgumentBody(rules=[], Conc=["We should buy a"], Ass=[])))

    assert set(payload["Argument"]) == {"rules", "Conc", "Ass"}
    assert "attack" not in payload["Argument"]
    assert "target" not in payload["Argument"]
