"""実験ランナー（experiments/dialogue/runners/run_dialectical.py）の、LLM を使わない部分のテスト."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import pytest

from experiments.dialogue.common import TokenUsageTracker
from experiments.dialogue.runners import run_dialectical as rd
from src.agent_migration.argumentation.dialectical import (
    Antecedent,
    Argument,
    Attack,
    CannotAttack,
    DialecticalProtocol,
    MainArgument,
    Phase1,
    Rule,
)
from src.agent_migration.argumentation.free_debate import DebateTurn, FreeDebate
from src.agent_migration.argumentation.mad import MAD
from src.agent_migration.argumentation.no_schema import NoSchemaProtocol

TOPIC = {"question": "Q?", "agent1_stance": "S1", "agent2_stance": "S2"}


class FakeAgent:
    def __init__(self, fail_on_chat: bool = False):
        self.fail_on_chat = fail_on_chat

    async def structured(self, prompt, schema, system=None):
        if schema is DebateTurn:
            return DebateTurn(argument="a point", has_new_point=True)
        if schema is Phase1:
            r = Rule(antecedent=Antecedent(strong_statements=[], weak_statements=[]), consequent="claim")
            return Phase1(move=MainArgument(argument_type="main_argument", argument=Argument(rules=[r])))
        assert schema is Attack
        return Attack(move=CannotAttack(attack_type="cannot_attack", reason="x"))

    async def chat(self, prompt, system=None):
        if self.fail_on_chat:
            raise RuntimeError("boom")
        return SimpleNamespace(content="FINAL")


def write_topic(tmp_path):
    d = tmp_path / "datasets" / "Cat"
    d.mkdir(parents=True)
    f = d / "topic_a.json"
    f.write_text(json.dumps(TOPIC), encoding="utf-8")
    return f


def agents(a: Any = None) -> rd.Agents:
    a = a or FakeAgent()
    return rd.Agents(
        ag1=a, ag2=a, helper=a, final_judge=a,
        trackers={"agents": TokenUsageTracker("gpt-5.4-nano"), "judge": TokenUsageTracker("gpt-5.4-mini")},
    )


def test_log_is_saved_under_experiment_turns_raw_dialogue(tmp_path):
    f = write_topic(tmp_path)
    root = tmp_path / "logs" / "experiment_20260101_000000"
    path = asyncio.run(rd.run_one("schema", f, 7, root, None, agents()))
    assert path.parent == root / "turns7" / "raw_dialogue" / "Cat" / "topic_a"
    assert path.name.startswith("schema_") and path.suffix == ".json"
    log = json.loads(path.read_text(encoding="utf-8"))
    assert log["method"] == "schema" and log["question"] == "Q?" and log["final_answer"] == "FINAL"
    assert log["metrics"]["closed_by"] == "justified" and log["metrics"]["max_dialogue_turns"] == 7
    assert log["history"] == [{"role": "ag1", "content": log["history"][0]["content"], "status": "justified", "kind": "main"}]
    # 既存の評価スクリプトが読む形
    assert log["dialogue_history"] == [
        {
            "id": "h0",
            "agent": "AG1",
            "argument": {"Argument": {"rules": [{"antecedent": {"strong": [], "weak_negation": []}, "consequent": "claim"}], "Conc": ["claim"], "Ass": []}},
            "type": "main",
            "proponent": "AG1",
            "status": "justified",
        }
    ]
    assert log["consensus_reached"] is True and log["integrated_rules"] == [] and log["metrics"]["total_dialogue_turns"] == 2
    assert "error" not in log


def test_run_index_prefix_is_added_for_multiple_runs(tmp_path):
    f = write_topic(tmp_path)
    path = asyncio.run(rd.run_one("schema", f, 5, tmp_path / "root", 2, agents()))
    assert path.name.startswith("02_schema_")


def test_partial_history_is_saved_when_an_error_occurs(tmp_path):
    f = write_topic(tmp_path)
    path = asyncio.run(rd.run_one("schema", f, 5, tmp_path / "root", None, agents(FakeAgent(fail_on_chat=True))))  # 最終回答の chat() で失敗する
    log = json.loads(path.read_text(encoding="utf-8"))
    assert log["error"].startswith("RuntimeError: boom")
    assert len(log["dialogue_history"]) == 1 and log["final_answer"] is None


def test_protocol_selection_and_topic_resolution() -> None:
    a = agents()
    kinds = {
        "schema": DialecticalProtocol, "no_schema": NoSchemaProtocol, "free_debate": FreeDebate, "mad": MAD, "mad_synthesis": MAD,
    }
    for method, cls in kinds.items():
        assert type(rd.make_protocol(method, TOPIC, 3, a)) is cls
    assert rd.make_protocol("mad", TOPIC, 3, a).use_synthesis is False  # type: ignore[attr-defined]
    assert rd.make_protocol("mad_synthesis", TOPIC, 3, a).use_synthesis is True  # type: ignore[attr-defined]
    with pytest.raises(ValueError):
        rd.make_protocol("nope", TOPIC, 3, a)
    assert len(rd.resolve_topics("all")) > 90
    assert rd.resolve_topics("datasets/Education/free_college.json")[0].stem == "free_college"


def test_baseline_log_has_turn_kinds_and_the_judge_answer(tmp_path) -> None:
    f = write_topic(tmp_path)
    root = tmp_path / "root"
    path = asyncio.run(rd.run_one("mad", f, 2, root, None, agents()))
    log = json.loads(path.read_text(encoding="utf-8"))
    assert log["method"] == "mad" and path.name.startswith("mad_")
    assert [h["kind"] for h in log["history"]] == ["turn", "turn"] and log["final_answer"] == "FINAL"
    # 比較手法の発言は、type を持たない（既存と同じ）
    assert [(h["agent"], "type" in h) for h in log["dialogue_history"]] == [("AG1", False), ("AG2", False)]
    assert log["metrics"]["closed_by"] == "turn_limit"


def test_dry_run_needs_no_api_key_and_calls_no_llm(capsys, monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    saved = asyncio.run(
        rd.main(["Education", "datasets/Elections_Presidents/election_day.json", "--methods", "schema,mad", "--turns", "10", "20", "--runs", "2", "--dry-run"])
    )
    out = capsys.readouterr().out
    assert saved == [] and "turns=[10, 20]" in out and "turns<N>/raw_dialogue" in out and "同時 8" in out
    assert "methods=['schema', 'mad']" in out


def test_unknown_method_is_rejected() -> None:
    with pytest.raises(SystemExit):
        asyncio.run(rd.main(["Education", "--methods", "schema,nope", "--dry-run"]))


def test_the_log_is_readable_by_the_existing_evaluators() -> None:
    """既存の評価（SVI など）は、議論の書き起こしを使う。新しいログから、空でない書き起こしが作られること."""
    from experiments.eval.scoring.evaluation import build_eval_input
    from src.agent_migration.argumentation.dialectical import Rebut

    def rule(c: str, strong: list[str] | None = None, weak: list[str] | None = None) -> Rule:
        return Rule(antecedent=Antecedent(strong_statements=strong or [], weak_statements=weak or []), consequent=c)

    history = [
        rd.Message("ag1", None, "main", Argument(rules=[rule("p"), rule("we should", ["p"], ["no evidence otherwise"])]), phase="main", proponent="ag1"),
        rd.Message(
            "ag2", Rebut(attack_type="rebut", target="we should", argument=Argument(rules=[rule("we should not")])),
            "attack", Argument(rules=[rule("we should not")]), phase="defeat", proponent="ag1", attack="rebut", target_index=0, target_statement="we should",
        ),
        rd.Message("ag1", "RULE", "integrate"),
    ]
    entries = rd.legacy_dialogue_history(history, {0: "defensible"})
    assert [e["id"] for e in entries] == ["h0", "h1"]  # 統合の rule は入らない
    assert entries[1]["type"] == "defeat" and entries[1]["target_id"] == "h0" and entries[1]["target_statement"] == "we should"
    assert entries[0]["status"] == "defensible" and entries[0]["argument"]["Argument"]["Ass"] == ["no evidence otherwise"]
    log = {"question": "Q", "agent1_stance": "s1", "agent2_stance": "s2", "dialogue_history": entries, "final_answer": "F", "integrated_rules": []}
    transcript = build_eval_input(log)["debate_transcript"]
    assert "[Turn 1] AG1 (new argument)" in transcript and "[Turn 2] AG2 (responding to [Turn 1])" in transcript
    assert "we should not" in transcript and "(no argument)" not in transcript

