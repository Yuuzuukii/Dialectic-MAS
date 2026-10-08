"""議論の建設性の採点スクリプト（eval_constructiveness）の、LLM を使わない部分のテスト."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from experiments.eval.runners import eval_constructiveness as script


def test_parse_source_splits_folder_and_methods() -> None:
    root, methods = script.parse_source("logs/fin:free_debate,mad")
    assert root == Path("logs/fin")
    assert methods == frozenset({"free_debate", "mad"})


def test_parse_source_rejects_missing_methods() -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        script.parse_source("logs/fin")


def test_summary_ignores_failed_logs_but_counts_them() -> None:
    rows = [
        {"method": "schema", "constructiveness": 6},
        {"method": "schema", "constructiveness": 8},
        {"method": "schema", "constructiveness": None},
        {"method": "mad", "constructiveness": 4},
    ]
    summary = script.summarize(rows)
    assert summary["schema"] == {
        "n_logs": 3,
        "n_scored": 2,
        "constructiveness_mean": 7.0,
    }
    assert summary["mad"]["n_scored"] == 1
