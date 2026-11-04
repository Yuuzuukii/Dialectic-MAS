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


def test_invalid_attempts_are_drawn_as_leaves_under_their_target() -> None:
    log = {
        "dialogue_history": [_rec("h0", "main", "AG1"), _rec("h1", "defeat", "AG2", "h0")],
        "invalid_attempts": [
            {
                "role": "ag1",
                "declared": "rebut",
                "reason": "strictly defeat でない",
                "target_index": 1,
                "main_index": 0,
                "content": {"argument": {"rules": [{"consequent": "retry text"}]}},
            },
            {"role": "ag1", "declared": "undercut", "reason": "defeat でない", "target_index": None, "main_index": 0, "content": "free text"},
        ],
    }
    elements, _ = build_run("schema", log)
    nodes = {e["data"]["id"]: e for e in elements if e.get("classes") == "invalid"}
    edges = {e["data"]["id"]: e["data"] for e in elements if str(e["data"].get("id", "")).startswith("e-x")}

    assert set(nodes) == {"x0", "x1"}
    assert edges["e-x0"]["target"] == "h1"  # 反撃の対象（O の攻撃）の下に付く
    assert edges["e-x1"]["target"] == "h0"  # 対象の番号がなければ、主張に付く
    assert "retry text" in nodes["x0"]["data"]["label"]
    assert "strictly defeat でない" in nodes["x0"]["data"]["detail"]
    assert nodes["x0"]["position"]["y"] > next(e for e in elements if e["data"].get("id") == "h1")["position"]["y"]
