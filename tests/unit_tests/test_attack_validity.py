"""攻撃の監査（eval_attack_validity）の、LLM を使わない部分のテスト."""

from __future__ import annotations

from typing import Any

from experiments.eval.runners import eval_attack_validity as av

LOG: dict[str, Any] = {
    "method": "no_schema",
    "question": "Q?",
    "dialogue_history": [
        {"id": "a", "agent": "AG1", "type": "main", "argument": "main text"},
        {"id": "b", "agent": "AG2", "type": "defeat", "argument": "attack on a", "attack": "rebut", "target_id": "a", "target_statement": "stmt"},
        {"id": "c", "agent": "AG1", "type": "counter", "argument": "counter to b", "attack": "rebut", "target_id": "b"},
        {"id": "d", "agent": "AG2", "type": "defeat", "argument": "dangling", "attack": "rebut", "target_id": "zzz"},
    ],
    "attempt_log": [
        {"kind": "attack_rejected", "phase": "defeat", "agent": "AG2", "target_id": "b", "reason": "x"},
        {"kind": "no_attack", "phase": "defeat", "agent": "AG2", "target_id": "a", "reason": "y"},
    ],
}


def test_attack_turns_keep_only_attacks_whose_target_is_in_the_log() -> None:
    items = av.attack_turns(LOG)
    assert [i["turn"] for i in items] == [2, 3]
    assert items[0]["target_text"] == "main text" and items[0]["attack_text"] == "attack on a"


def test_implementation_rejection_is_marked_from_the_attempt_log() -> None:
    items = av.attack_turns(LOG)
    assert items[0]["rejected_by_implementation"] is True  # b は却下の記録がある
    assert items[1]["rejected_by_implementation"] is False  # no_attack は却下ではない


def test_prompt_hides_method_and_declared_attack_type() -> None:
    prompt = av.build_prompt("Q?", av.attack_turns(LOG)[0])
    assert "main text" in prompt and "attack on a" in prompt and "stmt" in prompt
    for hidden in ("no_schema", "rebut", "defeat", "counter"):
        assert hidden not in prompt


def test_prompt_marks_missing_declared_statement() -> None:
    assert "(none declared)" in av.build_prompt("Q?", av.attack_turns(LOG)[1])


def test_summary_reports_valid_rate_and_agreement_with_rejection() -> None:
    def row(method: str, kind: str, rejected: bool, present: bool | None) -> dict[str, Any]:
        return {
            "method": method,
            "type": "defeat",
            "attack_kind": kind,
            "rejected_by_implementation": rejected,
            "declared_statement_present": present,
        }

    rows = [
        row("schema", "contradicts_conclusion", False, True),
        row("schema", "neither", True, False),
        row("schema", "both", False, None),
        row("no_schema", "neither", False, None),
    ]
    s = av.summarize(rows)
    assert s["schema"]["valid_attack_rate"] == round(2 / 3, 4)
    assert s["schema"]["valid_rate_among_rejected"] == 0.0 and s["schema"]["valid_rate_among_accepted"] == 1.0
    assert s["schema"]["declared_statement_present_rate"] == 0.5
    assert s["no_schema"]["valid_attack_rate"] == 0.0


def test_sampling_is_reproducible_and_limited(tmp_path: Any) -> None:
    import json

    for i in range(3):
        d = tmp_path / "turns10" / "raw_dialogue" / "cat" / "topic"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{i}.json").write_text(json.dumps(LOG), encoding="utf-8")
    paths = sorted(tmp_path.glob("turns*/raw_dialogue/*/*/*.json"))
    first = av.sample_items(paths, {"no_schema"}, 4, seed=1)
    second = av.sample_items(paths, {"no_schema"}, 4, seed=1)
    assert len(first["no_schema"]) == 4
    assert [(p.name, i["turn"]) for p, _, i in first["no_schema"]] == [(p.name, i["turn"]) for p, _, i in second["no_schema"]]
