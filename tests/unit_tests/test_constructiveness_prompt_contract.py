"""Constructiveness 評価の手法中立性・入力分離契約を固定するテスト."""

# ruff: noqa: E402

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.eval.scoring import evaluation_ranking, evaluation_rubrics
from experiments.eval.scoring.evaluation_pairwise import (
    PAIRWISE_CONSTRUCTIVENESS_BATCH_INSTRUCTION,
    PAIRWISE_CONSTRUCTIVENESS_INSTRUCTION,
)


def test_constructiveness_prompt_is_proportion_based_and_method_neutral() -> None:
    prompt = evaluation_rubrics.CONSTRUCTIVENESS_INSTRUCTION

    assert "<evaluation_units>" in prompt
    assert "NON-ADAPTIVE REVISION" in prompt
    assert "Merely quoting or naming a specific target is NOT enough" in prompt
    assert "PROPORTION and" in prompt
    assert "not their raw count or transcript length" in prompt
    assert "Do NOT judge factual correctness" in prompt
    assert "Do NOT reward a structured format" in prompt
    assert "one or two lapses" not in prompt
    assert "Perfect scores are rare" not in prompt


def test_related_constructiveness_prompts_use_the_same_scope_boundaries() -> None:
    ranking = evaluation_ranking.RANKING_INSTRUCTION
    pairwise_prompts = (
        PAIRWISE_CONSTRUCTIVENESS_INSTRUCTION,
        PAIRWISE_CONSTRUCTIVENESS_BATCH_INSTRUCTION,
    )

    assert "PROPORTION and SEVERITY" in ranking
    assert "Do not penalize a debate merely because it is longer" in ranking
    assert "Merely quoting a target is not sufficient" in ranking
    for prompt in pairwise_prompts:
        assert "Do NOT judge factual correctness" in prompt
        assert "Do NOT require novelty" in prompt
        assert "load-bearing" in prompt
        assert "Adds new reasoning" not in prompt


def test_combined_evaluation_excludes_integrated_rules_from_constructiveness(
    monkeypatch: Any,
) -> None:
    build_calls: list[bool] = []
    received: dict[str, bool] = {}

    def fake_build_eval_input(
        _log: dict[str, Any], *, include_integrated_rules: bool = True
    ) -> dict[str, bool]:
        build_calls.append(include_integrated_rules)
        return {"include_integrated_rules": include_integrated_rules}

    def fake_constructiveness(
        eval_input: dict[str, bool], _evaluator: Any
    ) -> dict[str, int]:
        received["constructiveness"] = eval_input["include_integrated_rules"]
        return {"constructiveness": 8}

    def fake_constraint(
        eval_input: dict[str, bool], _evaluator: Any
    ) -> dict[str, int]:
        received["constraint"] = eval_input["include_integrated_rules"]
        return {"constraint_preservation": 7}

    monkeypatch.setattr(
        evaluation_rubrics, "build_eval_input", fake_build_eval_input
    )
    monkeypatch.setattr(
        evaluation_rubrics, "evaluate_constructiveness", fake_constructiveness
    )
    monkeypatch.setattr(
        evaluation_rubrics, "evaluate_constraint_preservation", fake_constraint
    )

    evaluator = type("Evaluator", (), {"model": "test-model"})()
    scores = evaluation_rubrics.evaluate_rubrics({}, evaluator)

    assert build_calls == [False, True]
    assert received == {"constructiveness": False, "constraint": True}
    assert scores["constructiveness"] == 8
    assert scores["constraint_preservation"] == 7
