"""最終回答を AG1 の役割で書き直す処理の単体テスト（LLM はモックする）."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from agent import final_answer
from experiments.dialogue.runners import refinalize_ag1_answer as runner

pytestmark = pytest.mark.anyio


def test_default_writer_keeps_the_neutral_prompt_and_ag1_adds_a_role_block() -> None:
    assert final_answer.final_system() == final_answer._FINAL_SYSTEM
    ag1 = final_answer.final_system("AG1")
    assert ag1.startswith("<role>\nYou are AG1 in this debate.")
    assert ag1.endswith(final_answer._FINAL_SYSTEM)
    assert "AG1 stance" in ag1


def _log(**extra: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "method": "schema",
        "question": "q",
        "agent1_stance": "s1",
        "agent2_stance": "s2",
        "dialogue_history": [{"agent": "AG1", "type": "main", "argument": "a"}],
        "final_answer": "old answer",
        "integrated_proposal": "kept proposal",
    }
    return base | extra


async def test_rewrite_reuses_the_stored_proposal_and_keeps_the_old_answer(
    monkeypatch,
) -> None:
    seen: dict[str, Any] = {}

    async def fake(**kwargs: Any) -> str:
        seen.update(kwargs)
        return "new answer"

    monkeypatch.setattr(runner, "answer_from_materials", fake)

    log = await runner.rewrite(_log())

    assert seen["writer"] == "AG1" and seen["integrated_proposal"] == "kept proposal"
    assert log["final_answer"] == "new answer"
    assert log["neutral_final_answer"] == "old answer"
    assert log["final_answer_writer"] == "AG1"
    assert log["integrated_proposal"] == "kept proposal"  # 議論と統合案は変えない


async def test_a_blank_proposal_is_passed_as_none(monkeypatch) -> None:
    seen: dict[str, Any] = {}

    async def fake(**kwargs: Any) -> str:
        seen.update(kwargs)
        return "x"

    monkeypatch.setattr(runner, "answer_from_materials", fake)

    await runner.rewrite(_log(integrated_proposal=None))

    assert seen["integrated_proposal"] is None


def test_collect_selects_by_the_method_in_the_log(tmp_path: Path) -> None:
    for name, method in (("a", "schema"), ("b", "mad")):
        path = (
            tmp_path / "turns10" / "raw_dialogue" / "cat" / "topic" / f"01_{name}.json"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"method": method}), encoding="utf-8")

    found = runner.collect(tmp_path, frozenset({"schema"}))

    assert [rel.name for _, rel in found] == ["01_a.json"]
