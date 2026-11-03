"""新しい弁証的議論の実験ランナー（experiments/dialogue/runners/run_dialectical.py）の、LLM を使わない部分のテスト."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from experiments.dialogue.common import TokenUsageTracker
from experiments.dialogue.runners import run_dialectical as rd
from src.agent_migration.argumentation.dialectical import (
    Antecedent,
    Argument,
    Attack,
    CannotAttack,
    MainArgument,
    Phase1,
    Rule,
)

TOPIC = {"question": "Q?", "agent1_stance": "S1", "agent2_stance": "S2"}


class FakeAgent:
    def __init__(self, fail_on_chat: bool = False):
        self.fail_on_chat = fail_on_chat

    async def structured(self, prompt, schema, system=None):
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


def trackers():
    return {"agents": TokenUsageTracker("gpt-5.4-nano"), "judge": TokenUsageTracker("gpt-5.4-mini")}


def test_log_is_saved_under_experiment_turns_raw_dialogue(tmp_path):
    f = write_topic(tmp_path)
    root = tmp_path / "logs" / "experiment_20260101_000000"
    a = FakeAgent()
    path = asyncio.run(rd.run_one("schema", f, 7, root, None, a, a, a, trackers()))
    assert path.parent == root / "turns7" / "raw_dialogue" / "Cat" / "topic_a"
    assert path.name.startswith("schema_") and path.suffix == ".json"
    log = json.loads(path.read_text(encoding="utf-8"))
    assert log["method"] == "schema" and log["question"] == "Q?" and log["final_answer"] == "FINAL"
    assert log["metrics"]["closed_by"] == "justified" and log["metrics"]["max_dialogue_turns"] == 7
    assert log["dialogue_history"] == [
        {"role": "ag1", "content": log["dialogue_history"][0]["content"], "status": "justified"}
    ]
    assert "error" not in log and log["invalid_attempts"] == []


def test_run_index_prefix_is_added_for_multiple_runs(tmp_path):
    f = write_topic(tmp_path)
    a = FakeAgent()
    path = asyncio.run(rd.run_one("schema", f, 5, tmp_path / "root", 2, a, a, a, trackers()))
    assert path.name.startswith("02_schema_")


def test_partial_history_is_saved_when_an_error_occurs(tmp_path):
    f = write_topic(tmp_path)
    a = FakeAgent(fail_on_chat=True)  # 最終回答の chat() で失敗する
    path = asyncio.run(rd.run_one("schema", f, 5, tmp_path / "root", None, a, a, a, trackers()))
    log = json.loads(path.read_text(encoding="utf-8"))
    assert log["error"].startswith("RuntimeError: boom")
    assert len(log["dialogue_history"]) == 1 and log["final_answer"] is None


def test_protocol_selection_and_topic_resolution(tmp_path):
    a = FakeAgent()
    from src.agent_migration.argumentation.dialectical import DialecticalProtocol
    from src.agent_migration.argumentation.no_schema import NoSchemaProtocol

    assert type(rd.make_protocol("schema", TOPIC, 3, a, a, a)) is DialecticalProtocol
    assert type(rd.make_protocol("no_schema", TOPIC, 3, a, a, a)) is NoSchemaProtocol
    assert len(rd.resolve_topics("all")) > 90
    assert rd.resolve_topics("datasets/Education/free_college.json")[0].stem == "free_college"


def test_dry_run_needs_no_api_key_and_calls_no_llm(capsys, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    saved = asyncio.run(rd.main(["schema", "Education", "--turns", "10", "20", "--runs", "2", "--dry-run"]))
    out = capsys.readouterr().out
    assert saved == [] and "turns=[10, 20]" in out and "回" in out and "turns<N>/raw_dialogue" in out
