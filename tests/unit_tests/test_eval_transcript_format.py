"""評価用 transcript の統一フォーマット（docs/eval_transcript_format_spec.md §4-5）のテスト."""

from __future__ import annotations

import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).parents[2] / "experiments" / "eval" / "scoring" / "evaluation.py"
spec = importlib.util.spec_from_file_location("eval_evaluation", MODULE_PATH)
assert spec is not None and spec.loader is not None
evaluation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluation)


def _schema_argument(strongs, conclusion, assumptions=()):
    return {
        "Argument": {
            "rules": [
                {
                    "antecedent": {
                        "strong": list(strongs),
                        "weak_negation": list(assumptions),
                    },
                    "consequent": conclusion,
                }
            ],
            "Conc": [conclusion],
            "Ass": list(assumptions),
        }
    }


def test_schema_main_argument_rendered_as_utterance() -> None:
    log = {
        "question": "Q?",
        "agent1_stance": "s1",
        "agent2_stance": "s2",
        "dialogue_history": [
            {
                "id": "arg-1",
                "agent": "AG1",
                "type": "main",
                "argument": _schema_argument(
                    ["'a' is in stock.", "If something is in stock, we can buy it."],
                    "We should buy 'a'.",
                ),
            }
        ],
        "final_answer": "buy a",
    }
    transcript = evaluation.build_eval_input(log)["debate_transcript"]

    assert "[Turn 1] AG1 (new argument)" in transcript
    assert (
        "'a' is in stock. If something is in stock, we can buy it. "
        "Therefore, We should buy 'a'." in transcript
    )
    # 生JSONやフィールド名は描画されない
    assert '"rules"' not in transcript
    assert "Conc" not in transcript


def test_schema_attack_turn_names_target_statement() -> None:
    log = {
        "question": "Q?",
        "agent1_stance": "s1",
        "agent2_stance": "s2",
        "dialogue_history": [
            {
                "id": "arg-1",
                "agent": "AG1",
                "type": "main",
                "argument": _schema_argument(["p"], "We should buy 'a'."),
            },
            {
                "id": "arg-2",
                "agent": "AG2",
                "type": "defeat",
                "attack": "rebut",
                "target_id": "arg-1",
                "target_field": "Conc",
                "target_statement": "We should buy 'a'.",
                "argument": _schema_argument(
                    ["'a' is out of stock.", "If something is out of stock, we don't buy it."],
                    "We should not buy 'a'.",
                ),
            },
        ],
        "final_answer": "x",
    }
    transcript = evaluation.build_eval_input(log)["debate_transcript"]

    assert "[Turn 2] AG2 (responding to [Turn 1])" in transcript
    assert (
        'I disagree with your conclusion that "We should buy \'a\'". '
        "'a' is out of stock. If something is out of stock, we don't buy it. "
        "Therefore, We should not buy 'a'." in transcript
    )


def test_schema_undercut_uses_premise_wording_and_assumptions_are_rendered() -> None:
    log = {
        "question": "Q?",
        "agent1_stance": "s1",
        "agent2_stance": "s2",
        "dialogue_history": [
            {
                "id": "arg-1",
                "agent": "AG1",
                "type": "main",
                "argument": _schema_argument(
                    ["p"], "c", assumptions=["stock levels are reliable"]
                ),
            },
            {
                "id": "arg-2",
                "agent": "AG2",
                "type": "defeat",
                "attack": "undercut",
                "target_id": "arg-1",
                "target_field": "Ass",
                "target_statement": "stock levels are reliable",
                "argument": _schema_argument(["q"], "not c"),
            },
        ],
        "final_answer": "x",
    }
    transcript = evaluation.build_eval_input(log)["debate_transcript"]

    assert (
        'Your premise that "stock levels are reliable" does not hold.' in transcript
    )
    assert "(This relies on the assumption that stock levels are reliable.)" in transcript


def test_no_schema_keeps_raw_text_with_attack_label() -> None:
    log = {
        "question": "Q?",
        "agent1_stance": "s1",
        "agent2_stance": "s2",
        "dialogue_history": [
            {
                "id": "arg-1",
                "agent": "AG1",
                "type": "main",
                "argument": "We should buy a because it is cheap.",
            },
            {
                "id": "arg-2",
                "agent": "AG2",
                "type": "defeat",
                "attack": "undercut",
                "target_id": "arg-1",
                "target_field": "Ass",
                "target_statement": "a is cheap",
                "argument": "Actually a is expensive, so the reasoning fails.",
            },
        ],
        "final_answer": "x",
    }
    transcript = evaluation.build_eval_input(log)["debate_transcript"]

    # 原文は書き換えない
    assert "Actually a is expensive, so the reasoning fails." in transcript
    # ラベル側に攻撃対象を明示する
    assert (
        '[Turn 2] AG2 (responding to [Turn 1], challenging its premise: "a is cheap")'
        in transcript
    )


def test_mad_free_debate_turns_render_plainly() -> None:
    log = {
        "question": "Q?",
        "agent1_stance": "s1",
        "agent2_stance": "s2",
        "dialogue_history": [
            {"agent": "AG1", "round": 1, "argument": "Yes, because X."},
            {"agent": "AG2", "round": 1, "argument": "No, because Y."},
        ],
        "final_answer": "x",
    }
    transcript = evaluation.build_eval_input(log)["debate_transcript"]

    assert "[Turn 1] AG1:\nYes, because X." in transcript
    assert "[Turn 2] AG2:\nNo, because Y." in transcript
