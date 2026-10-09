"""議論木ビューアの単体テスト: 弾かれた攻撃と却下された下書きを、点線の枠で描く."""

from __future__ import annotations

from typing import Any

from experiments.eval.plots.plot_argument_network import build_run


def _rec(rid: str, rtype: str, agent: str, target: str | None = None) -> dict[str, Any]:
    rec: dict[str, Any] = {"id": rid, "type": rtype, "agent": agent, "argument": f"text {rid}"}
    if target:
        rec.update(target_id=target, attack="rebut")
    return rec


def _log() -> dict[str, Any]:
    return {
        "dialogue_history": [_rec("m1", "main", "AG1"), _rec("d1", "defeat", "AG2", "m1")],
        "attempt_log": [
            {"kind": "attack_rejected", "agent": "AG2", "target_id": "d1", "reason": "does not oppose"}
        ],
        "judge_stats": {
            "judgements": [
                {"kind": "rebut", "attack_id": "d1", "holds": False, "reason": "same stance", "context": ""}
            ]
        },
        "discarded_drafts": [
            {"agent": "AG2", "kind": "attack", "target_id": "m1", "gave_up": False, "violations": ["bad"]},
            {"agent": "AG1", "kind": "main", "gave_up": True, "violations": ["worse"]},
        ],
    }


def test_rejected_attack_is_dotted_and_shows_the_judge_reason() -> None:
    elements, _ = build_run("schema", _log())
    node = next(e for e in elements if e["data"].get("id") == "d1")

    assert node["classes"] == "rejected"
    assert "does not oppose" in node["data"]["detail"]
    assert "same stance" in node["data"]["detail"]
    main = next(e for e in elements if e["data"].get("id") == "m1")
    assert "classes" not in main


def test_discarded_drafts_become_dotted_nodes_linked_to_their_target() -> None:
    elements, _ = build_run("no_schema", _log())
    drafts = [e for e in elements if e.get("classes") == "discarded"]
    edges = [e for e in elements if str(e["data"].get("id", "")).startswith("discarded-e-")]

    assert len(drafts) == 2
    assert [e["data"]["target"] for e in edges] == ["m1"]  # 対象のない下書きは、辺なし
    assert "断念" in drafts[1]["data"]["label"]
