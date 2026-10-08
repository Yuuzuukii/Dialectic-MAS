"""再構成の判定（eval_reframing）の、LLM を使わない部分のテスト."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from experiments.eval.runners import eval_reframing as rf

HISTORY = [
    {"agent": "AG1", "type": "main", "argument": "ag1 first"},
    {"agent": "AG2", "type": "defeat", "argument": "ag2 first"},
    {"agent": "AG1", "type": "counter", "argument": "ag1 second"},
    {"agent": "AG2", "type": "defeat", "argument": "ag2 second"},
]
LOG = {"method": "schema", "question": "Q?", "agent1_stance": "secret stance", "dialogue_history": HISTORY}


def test_prompt_shows_own_turns_latest_opponent_turn_and_hides_metadata() -> None:
    prompt = rf.build_prompt("Q?", HISTORY, 3)
    assert "[Turn 2]\nag2 first" in prompt and "[Turn 3]\nag1 second" in prompt and "[Turn 4]\nag2 second" in prompt
    assert "ag1 first" not in prompt
    for hidden in ("schema", "defeat", "counter", "secret stance"):
        assert hidden not in prompt


def test_prompt_separates_reframing_from_adding_facts_and_ignores_vocabulary() -> None:
    prompt = rf.build_prompt("Q?", HISTORY, 2)
    assert "WITHIN the same framing is not a reconstruction" in prompt
    assert "Do not reward words such as" in prompt


def test_failed_turn_is_recorded_and_excluded_from_rates(tmp_path: Path, monkeypatch: Any) -> None:
    path = tmp_path / "log.json"
    path.write_text(json.dumps(LOG), encoding="utf-8")
    replies = iter([rf.ReframingJudgement(reframes=True, reframe_kind="introduces_criterion", what_reframed="x"), RuntimeError("boom")])

    def fake_judge(model_name: str, prompt: str) -> rf.ReframingJudgement:
        reply = next(replies)
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(rf, "_judge", fake_judge)
    row = rf.evaluate_log("m", path)
    assert row["n_judged"] == 1 and row["n_failed"] == 1 and row["reframe_rate"] == 1.0 and row["n_reframes"] == 1


def test_summary_reports_rate_and_kind_share() -> None:
    def log(method: str, flags: list[bool]) -> dict[str, Any]:
        turns = [
            {"turn": i + 2, "type": "counter", "reframes": f, "reframe_kind": "redefines_concept" if f else "none"}
            for i, f in enumerate(flags)
        ]
        return {"method": method, "turns": turns, "reframe_rate": sum(flags) / len(flags), "n_reframes": sum(flags)}

    summary = rf.summarize([log("schema", [True, False, False, False]), log("no_schema", [False, False])])
    assert summary["schema"]["reframe_rate_mean"] == 0.25
    assert summary["schema"]["reframe_kind_share"] == {"none": 0.75, "redefines_concept": 0.25}
    assert summary["no_schema"]["reframes_per_log"] == 0
