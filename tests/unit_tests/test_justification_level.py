"""正当化の水準の評価（eval_justification_level）の、Jev を使わない部分のテスト."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from experiments.eval.runners import eval_justification_level as jl

HISTORY = [
    {"agent": "AG1", "type": "main", "argument": "ag1 first"},
    {"agent": "AG2", "type": "defeat", "argument": "ag2 first"},
    {"agent": "AG1", "type": "counter", "argument": "ag1 second"},
]
LOG = {
    "method": "schema",
    "question": "Q?",
    "agent1_stance": "secret stance 1",
    "agent2_stance": "secret stance 2",
    "dialogue_history": HISTORY,
}


def test_level_takes_the_highest_satisfied_stage() -> None:
    assert jl.level_of(0.9, 0.9, 0.9, 0.5) == 3
    assert jl.level_of(0.9, 0.9, 0.2, 0.5) == 2
    assert jl.level_of(0.9, 0.2, 0.2, 0.5) == 1
    assert jl.level_of(0.2, 0.2, 0.2, 0.5) == 0


def test_expected_level_is_nested_and_between_zero_and_three() -> None:
    assert jl.expected_level(1.0, 1.0, 1.0) == 3.0
    assert jl.expected_level(0.0, 0.0, 0.0) == 0.0
    assert jl.expected_level(0.5, 0.9, 0.9) == 1.5  # 上の段階は下の段階の確率を超えない
    assert jl.expected_level(1.0, 0.5, 0.0) == 1.5


def test_state_hides_stances_and_method_and_separates_the_turn() -> None:
    state = jl.build_state(LOG, HISTORY, 2)
    assert state["turn_under_review"] == "[Turn 3]\nag1 second"
    assert "ag1 first" in state["earlier_dialogue"] and "ag1 second" not in state["earlier_dialogue"]
    dumped = json.dumps(state)
    assert "secret stance" not in dumped and "schema" not in dumped
    assert jl.build_state(LOG, HISTORY, 0)["earlier_dialogue"] == "(no earlier turns)"


def test_failed_turn_is_recorded_as_none_and_excluded_from_means(tmp_path: Path, monkeypatch: Any) -> None:
    path = tmp_path / "log.json"
    path.write_text(json.dumps(LOG), encoding="utf-8")
    replies = iter(
        [
            {"reason": 0.9, "complete": 0.9, "two": 0.9},
            None,
            {"reason": 0.1, "complete": 0.1, "two": 0.1},
        ]
    )

    async def fake_judge(client: Any, state: dict[str, str]) -> dict[str, float] | None:
        return next(replies)

    monkeypatch.setattr(jl, "judge_turn", fake_judge)
    row = asyncio.run(jl.evaluate_log(object(), asyncio.Semaphore(1), path, 0.5))  # type: ignore[arg-type]
    assert row["n_failed"] == 1
    assert [t["level"] for t in row["turns"]] == [3, None, 0]
    assert row["level_mean"] == 1.5


def test_summary_reports_level_share_and_turn_type_means() -> None:
    def log(method: str, levels: list[int]) -> dict[str, Any]:
        turns = [
            {"turn": i + 1, "type": "defeat", "level": lv, "expected_level": float(lv)}
            for i, lv in enumerate(levels)
        ]
        mean = sum(levels) / len(levels)
        return {"method": method, "turns": turns, "level_mean": mean, "expected_level_mean": mean}

    summary = jl.summarize([log("schema", [2, 2, 0, 0]), log("no_schema", [1, 1, 1, 1])])
    assert summary["schema"]["level_share"] == {"0": 0.5, "2": 0.5}
    assert summary["schema"]["level_by_turn_type"] == {"defeat": 1.0}
    assert summary["schema"]["level_by_half"] == {"first_half": 2.0, "second_half": 0.0}
    assert summary["no_schema"]["level_mean"] == 1.0
