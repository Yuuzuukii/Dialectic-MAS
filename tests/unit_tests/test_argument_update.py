"""意味的な更新の判定（eval_argument_update）の、LLM を使わない部分のテスト."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from experiments.eval.runners import eval_argument_update as au

HISTORY = [
    {"agent": "AG1", "type": "main", "argument": "ag1 first"},
    {"agent": "AG2", "type": "defeat", "argument": "ag2 first"},
    {"agent": "AG1", "type": "counter", "argument": "ag1 second"},
    {"agent": "AG2", "type": "defeat", "argument": "ag2 second"},
]
LOG = {"method": "schema", "question": "Q?", "agent1_stance": "secret stance", "dialogue_history": HISTORY}


def test_only_turns_with_both_an_own_earlier_turn_and_an_opponent_turn_are_applicable() -> None:
    assert au.applicable_turns(HISTORY) == [2, 3]  # 最初の応答（自分の過去の発言なし）は対象外


def test_prompt_shows_own_earlier_turns_the_latest_opponent_turn_and_the_turn() -> None:
    prompt = au.build_prompt("Q?", HISTORY, 3)
    assert "[Turn 2]\nag2 first" in prompt  # AG2 自身の過去の発言
    assert "[Turn 3]\nag1 second" in prompt  # 直前の相手の発言
    assert "[Turn 4]\nag2 second" in prompt  # 採点する発言
    assert "ag1 first" not in prompt  # 相手の過去の発言は、直前以外は見せない


def test_prompt_hides_method_attack_type_and_stance() -> None:
    prompt = au.build_prompt("Q?", HISTORY, 2)
    for hidden in ("schema", "defeat", "counter", "secret stance", "overruled"):
        assert hidden not in prompt


def test_prompt_tells_the_judge_not_to_reward_discourse_markers() -> None:
    prompt = au.build_prompt("Q?", HISTORY, 2)
    assert "Do not reward explicit discourse markers" in prompt
    assert "Do not penalize structured or rule-based formulations" in prompt


def test_failed_turn_is_recorded_and_excluded_from_rates(tmp_path: Path, monkeypatch: Any) -> None:
    path = tmp_path / "log.json"
    path.write_text(json.dumps(LOG), encoding="utf-8")
    replies = iter(
        [
            au.UpdateJudgement(responds=True, updates=True, update_kind="narrows_disagreement", what_changed="x"),
            RuntimeError("boom"),
        ]
    )

    def fake_judge(model_name: str, prompt: str) -> au.UpdateJudgement:
        reply = next(replies)
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(au, "_judge", fake_judge)
    row = au.evaluate_log("m", path)
    assert row["n_judged"] == 1 and row["n_failed"] == 1
    assert row["update_rate"] == 1.0 and row["responds_rate"] == 1.0
    assert row["turns"][1]["responds"] is None


def test_summary_reports_update_rate_and_kind_share() -> None:
    def log(method: str, updates: list[bool]) -> dict[str, Any]:
        turns = [
            {
                "turn": i + 2,
                "type": "counter",
                "responds": True,
                "updates": u,
                "update_kind": "narrows_disagreement" if u else "none",
            }
            for i, u in enumerate(updates)
        ]
        return {
            "method": method,
            "turns": turns,
            "responds_rate": 1.0,
            "update_rate": sum(updates) / len(updates),
        }

    summary = au.summarize([log("schema", [True, True, False, False]), log("no_schema", [False, False])])
    assert summary["schema"]["update_rate_mean"] == 0.5
    assert summary["schema"]["update_kind_share"] == {"narrows_disagreement": 0.5, "none": 0.5}
    assert summary["schema"]["updates_per_log"] == 2
    assert summary["no_schema"]["update_rate_by_turn_type"] == {"counter": 0.0}
