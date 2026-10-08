"""反論への敬意の評価（eval_counterargument_respect）の、Jev を使わない部分のテスト."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from experiments.eval.runners import eval_counterargument_respect as cr

HISTORY = [
    {"agent": "AG1", "type": "main", "argument": "ag1 first"},
    {"agent": "AG1", "type": "main", "argument": "ag1 extra"},
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


def test_only_turns_with_an_earlier_opponent_turn_are_applicable() -> None:
    assert cr.applicable_turns(HISTORY) == [2, 3]  # 相手の発言がまだない発言は対象外


def test_answered_turn_is_the_latest_opponent_turn() -> None:
    assert cr.last_opponent_turn(HISTORY, 3) == 2
    assert cr.last_opponent_turn(HISTORY, 2) == 1


def test_level_follows_the_paper_stages() -> None:
    assert cr.level_of(0.1, 0.9, 0.9, 0.5) == 0  # 取り上げていなければ、他に関わらず 0
    assert cr.level_of(0.9, 0.9, 0.9, 0.5) == 3  # 評価があれば、貶す発言があっても 3
    assert cr.level_of(0.9, 0.1, 0.9, 0.5) == 1
    assert cr.level_of(0.9, 0.1, 0.1, 0.5) == 2


def test_expected_level_weights_the_stages_by_probability() -> None:
    assert cr.expected_level(1.0, 1.0, 0.0) == 3.0
    assert cr.expected_level(1.0, 0.0, 1.0) == 1.0
    assert cr.expected_level(1.0, 0.0, 0.0) == 2.0
    assert cr.expected_level(0.0, 1.0, 0.0) == 0.0
    assert cr.expected_level(0.5, 0.0, 0.0) == 1.0


def test_state_separates_the_answered_argument_and_hides_stances_and_method() -> None:
    state = cr.build_state(LOG, HISTORY, 3)
    assert state["other_sides_argument"] == "[Turn 3]\nag2 first"
    assert state["turn_under_review"] == "[Turn 4]\nag1 second"
    assert "ag2 first" in state["earlier_dialogue"] and "ag1 second" not in state["earlier_dialogue"]
    dumped = json.dumps(state)
    assert "secret stance" not in dumped and "schema" not in dumped


def test_failed_turn_is_recorded_as_none_and_excluded_from_means(tmp_path: Path, monkeypatch: Any) -> None:
    path = tmp_path / "log.json"
    path.write_text(json.dumps(LOG), encoding="utf-8")
    replies = iter([{"acknowledges": 0.9, "valued": 0.9, "degraded": 0.1}, None])

    async def fake_judge(client: Any, state: dict[str, str]) -> dict[str, float] | None:
        return next(replies)

    monkeypatch.setattr(cr, "judge_turn", fake_judge)
    row = asyncio.run(cr.evaluate_log(object(), asyncio.Semaphore(1), path, 0.5))  # type: ignore[arg-type]
    assert row["n_turns"] == 2 and row["n_failed"] == 1
    assert [t["level"] for t in row["turns"]] == [3, None]
    assert row["level_mean"] == 3


def test_summary_reports_level_share_and_turn_type_means() -> None:
    def log(method: str, levels: list[int]) -> dict[str, Any]:
        turns = [
            {"turn": i + 2, "type": "counter", "level": lv, "expected_level": float(lv)}
            for i, lv in enumerate(levels)
        ]
        mean = sum(levels) / len(levels)
        return {
            "method": method,
            "turns": turns,
            "level_mean": mean,
            "expected_level_mean": mean,
            "acknowledges_mean": 1.0,
            "valued_mean": 0.5,
        }

    summary = cr.summarize([log("schema", [3, 3, 0, 0]), log("no_schema", [2, 2, 2, 2])])
    assert summary["schema"]["level_share"] == {"0": 0.5, "3": 0.5}
    assert summary["schema"]["level_by_turn_type"] == {"counter": 1.5}
    assert summary["no_schema"]["level_mean"] == 2.0
