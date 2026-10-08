"""発言ごとの新規性判定（eval_turn_novelty）の、LLM を使わない部分のテスト."""

from __future__ import annotations

from experiments.eval.runners import eval_turn_novelty as novelty

HISTORY = [
    {"agent": "AG1", "type": "main", "argument": "ag1 first"},
    {"agent": "AG2", "type": "defeat", "argument": "ag2 first"},
    {"agent": "AG1", "type": "counter", "argument": "ag1 second"},
    {"agent": "AG2", "type": "defeat", "argument": "ag2 second"},
    {"agent": "AG1", "type": "defeat", "argument": "ag1 third"},
]


def test_only_turns_with_an_earlier_turn_by_the_same_side_are_reviewed() -> None:
    assert novelty.reviewable_turns(HISTORY) == [2, 3, 4]


def test_prompt_shows_only_the_same_sides_earlier_turns() -> None:
    prompt = novelty.build_prompt("Q?", HISTORY, 4)
    assert "ag1 first" in prompt and "ag1 second" in prompt
    assert (
        "ag2 first" not in prompt and "ag2 second" not in prompt
    )  # 相手の発言は見せない
    assert "[Turn 5]\nag1 third" in prompt
    assert (
        "rebut" not in prompt and "overruled" not in prompt
    )  # 攻撃の種類・決着状態は見せない


def test_summary_counts_only_same_claim_same_derivation_as_repeats() -> None:
    def log(method: str, verdicts: list[tuple[str, str]]) -> dict[str, object]:
        turns = [
            {"turn": i, "agent": "AG1", "type": t, "verdict": v}
            for i, (t, v) in enumerate(verdicts)
        ]
        repeated = sum(v == novelty.REPEAT for _, v in verdicts)
        return {
            "method": method,
            "n_judged": len(verdicts),
            "n_repeat": repeated,
            "repeat_rate": repeated / len(verdicts),
            "turns": turns,
        }

    summary = novelty.summarize(
        [
            log(
                "schema",
                [
                    ("defeat", "same_claim_same_derivation"),
                    ("counter", "same_claim_new_derivation"),
                ],
            ),
            log(
                "no_schema",
                [("defeat", "new_claim"), ("counter", "same_claim_new_derivation")],
            ),
        ]
    )
    # 同じ主張でも、別の導出なら反復としない
    assert summary["schema"]["repeat_rate_mean"] == 0.5
    assert summary["schema"]["repeat_by_turn_type"] == {"counter": 0.0, "defeat": 1.0}
    assert summary["no_schema"]["repeat_rate_mean"] == 0.0
    assert summary["no_schema"]["verdict_share"] == {
        "new_claim": 0.5,
        "same_claim_new_derivation": 0.5,
    }


def test_prompt_separates_claim_from_derivation() -> None:
    prompt = novelty.build_prompt("Q?", HISTORY, 4)
    assert (
        "A different derivation of the" in prompt
        and "same conclusion is NOT a repetition" in prompt
    )
    assert "same_claim_same_derivation" in prompt
