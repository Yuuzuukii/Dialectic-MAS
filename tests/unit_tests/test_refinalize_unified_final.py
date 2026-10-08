"""既存ログの最終回答を共通の作り方で作り直すスクリプトの、LLM を使わない部分のテスト."""

from __future__ import annotations

from pathlib import Path

from experiments.dialogue.runners import refinalize_unified_final as script


def test_justified_argument_comes_from_the_justified_main() -> None:
    log = {
        "consensus_reached": True,
        "dialogue_history": [
            {"agent": "AG1", "type": "main", "argument": "weak", "status": "overruled"},
            {
                "agent": "AG2",
                "type": "main",
                "argument": "strong",
                "status": "justified",
            },
        ],
    }
    assert script.justified_argument_of(log) == "strong"


def test_no_justified_argument_when_not_resolved() -> None:
    log = {
        "consensus_reached": False,
        "dialogue_history": [
            {"agent": "AG1", "type": "main", "argument": "x", "status": "defensible"}
        ],
    }
    assert script.justified_argument_of(log) is None


def test_mad_logs_are_written_as_mad_synthesis() -> None:
    relative = Path("turns10/raw_dialogue/Cat/topic/01_mad_20261006_111111_000001.json")
    out = script.output_relative(relative, "mad")
    assert out.name == "01_mad_synthesis_20261006_111111_000001.json"
    assert script.output_relative(relative, "free_debate") == relative
