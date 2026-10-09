"""run ごとの集計（判定の呼び出し、書き直し）と、費用の内訳の単体テスト."""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from agent import arguments, attack_judge, run_stats
from agent.attack_judge import RebutJudgement
from agent.schema.llm_outputs import (
    AntecedentDraft,
    ArgumentDraft,
    MainArgumentAvailabilityOutput,
    RuleDraft,
)

pytestmark = pytest.mark.anyio

USAGE = {
    "gpt-5.4-mini": {
        "input_tokens": 1000,
        "output_tokens": 200,
        "total_tokens": 1200,
        "input_token_details": {"cache_read": 400},
    }
}


def _common() -> Any:
    path = Path(__file__).parents[2] / "experiments" / "dialogue" / "common.py"
    spec = importlib.util.spec_from_file_location("dialogue_common", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_usage_tokens_sums_models_and_reads_the_cache_reads() -> None:
    total = run_stats.usage_tokens(
        {**USAGE, "other": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}}
    )

    assert total == {
        "prompt_tokens": 1010,
        "cached_tokens": 400,
        "completion_tokens": 205,
        "total_tokens": 1215,
    }


def test_records_do_nothing_when_no_run_has_begun() -> None:
    run_stats._current.set(None)

    run_stats.record_judge("rebut", USAGE)
    run_stats.record_regeneration("main")  # 例外にならない


async def test_each_concurrent_run_keeps_its_own_counts() -> None:
    async def one_run(calls: int) -> dict[str, Any]:
        stats = run_stats.begin_run()
        for _ in range(calls):
            run_stats.record_judge("rebut", USAGE)
            await asyncio.sleep(0)  # 他の run と、交互に動かす
        run_stats.record_regeneration("attack")
        return stats.to_dict()

    first, second = await asyncio.gather(one_run(2), one_run(5))

    assert first["judge_calls"] == {"rebut": 2}
    assert second["judge_calls"] == {"rebut": 5}
    assert first["judge_tokens"]["prompt_tokens"] == 2000
    assert second["judge_tokens"]["prompt_tokens"] == 5000
    assert first["regenerations"] == second["regenerations"] == {"attack": 1}


async def test_a_judgement_is_counted_with_its_kind(monkeypatch) -> None:
    async def fake(messages, schema, **kwargs):
        return RebutJudgement(attack_conclusion_quote="q", rebuts=True, reason="r")

    monkeypatch.setattr(attack_judge, "chat_structured", fake)
    stats = run_stats.begin_run()

    await attack_judge.judge_rebut(
        SimpleNamespace(question="Q?", output_mode="schema"),
        SimpleNamespace(id="arg-a", argument="a", conclusions=[]),  # type: ignore[arg-type]
        "S",
    )

    assert stats.judge_calls == {"rebut": 1}


def _draft(*consequents: str) -> ArgumentDraft:
    return ArgumentDraft(
        rules=[
            RuleDraft(antecedent=AntecedentDraft(from_rules=[1] if i else []), consequent=c)
            for i, c in enumerate(consequents)
        ]
    )


async def test_rewrites_and_giving_up_are_counted(monkeypatch) -> None:
    bad = ArgumentDraft(rules=[RuleDraft(antecedent=AntecedentDraft(from_rules=[1]), consequent="p")])
    outputs = iter([bad, bad, bad])

    async def fake(messages: list[Any], schema: Any, **kwargs: Any) -> Any:
        return MainArgumentAvailabilityOutput(can_generate="YES", reason="ok", Argument=next(outputs))

    monkeypatch.setattr(arguments, "chat_structured", fake)
    stats = run_stats.begin_run()
    state = SimpleNamespace(
        question="Q?",
        agent1_stance="s1",
        agent2_stance="s2",
        debate_round=1,
        integrated_rules=[],
        output_mode="schema",
        current_argument=None,
        current_proponent="AG1",
        ag1_revision_context=None,
        ag2_revision_context=None,
        history=[],
    )

    await arguments.generate_main(state, "AG1")

    assert stats.regenerations == {"main": arguments.MAX_REGENERATIONS, "main_gave_up": 1}


def test_judge_stats_splits_the_cost_between_the_writer_and_the_judge(monkeypatch) -> None:
    common = _common()
    monkeypatch.delenv("JUDGE_MODEL", raising=False)
    tracker = common.TokenUsageTracker(model="gpt-5.4-nano")
    tracker.prompt_tokens, tracker.cached_tokens = 11_000, 4_400
    tracker.completion_tokens, tracker.total_tokens = 2_200, 13_200
    stats = run_stats.RunStats()
    stats.judge_tokens.update(prompt_tokens=1000, cached_tokens=400, completion_tokens=200, total_tokens=1200)
    stats.judge_calls = {"rebut": 3}

    data = common._judge_stats(tracker, stats)

    # 書き手（nano）: 入力 10000（うちキャッシュ 4000）、出力 2000。単価は 0.20 / 0.02 / 1.25。
    assert data["generator_cost_usd"] == round((6000 * 0.20 + 4000 * 0.02 + 2000 * 1.25) / 1e6, 6)
    # 判定（mini）: 入力 1000（うちキャッシュ 400）、出力 200。単価は 0.75 / 0.075 / 4.50。
    assert data["judge_cost_usd"] == round((600 * 0.75 + 400 * 0.075 + 200 * 4.50) / 1e6, 6)
    assert data["corrected_total_cost_usd"] == round(data["generator_cost_usd"] + data["judge_cost_usd"], 6)
    assert data["judge_calls"] == {"rebut": 3}
    assert data["tokens_included_in_metrics"] is True
    assert data["judge_model"] == "gpt-5.4-mini"


async def test_every_judgement_is_recorded_with_its_reason_and_inputs(monkeypatch) -> None:
    from agent.attack_judge import (
        PresumptionList,
        UndercutJudgement,
        assumptions_for,
        judge_rebut,
        judge_undercut,
        undercut_relation,
    )
    from agent.schema.state import ArgumentRecord

    replies = iter(
        [
            RebutJudgement(attack_conclusion_quote="a is dear", rebuts=True, reason="denies S"),
            UndercutJudgement(
                undercut_assumption_number=2,
                attack_conclusion_quote="a is discontinued",
                reason="establishes not-X",
            ),
            PresumptionList(presumptions=["unless it is recalled", "a phrase never written"]),
            UndercutJudgement(undercut_assumption_number=None, reason="no assumption is denied"),
        ]
    )

    async def fake(messages, schema, **kwargs):
        return next(replies)

    monkeypatch.setattr(attack_judge, "chat_structured", fake)
    stats = run_stats.begin_run()
    state = SimpleNamespace(question="Q?", output_mode="schema")
    attack = ArgumentRecord(type="defeat", argument="{}", support=[], agent="AG2")
    target = ArgumentRecord(type="main", argument="{}", support=[], agent="AG1")

    await judge_rebut(state, attack, "We should buy a", target)
    await judge_undercut(state, attack, target, ["a1", "a2"], context="declared")
    free = SimpleNamespace(question="Q?", output_mode="no_schema")
    free_target = ArgumentRecord(
        type="main", argument="Buy a unless it is recalled.", support=[], agent="AG1"
    )
    # 仮定の取り出しと、それを使った一般の undercut の確認（no_schema）
    assert await assumptions_for(free, free_target) == ["unless it is recalled"]
    await undercut_relation(free, attack, free_target, context="strict_defeat_check")

    kinds = [item["kind"] for item in stats.judgements]
    assert kinds == ["rebut", "undercut", "extract", "undercut"]
    rebut, undercut, extract, relation = stats.judgements
    assert rebut["reason"] == "denies S" and rebut["holds"] is True
    assert rebut["attack_conclusion_quote"] == "a is dear" and rebut["target_id"] == target.id
    assert undercut["assumption"] == "a2" and undercut["context"] == "declared"
    assert undercut["assumptions"] == ["a1", "a2"] and undercut["reason"] == "establishes not-X"
    assert extract["presumptions"] == ["unless it is recalled"]
    assert extract["dropped_not_verbatim"] == ["a phrase never written"]
    assert relation["context"] == "strict_defeat_check" and relation["holds"] is False
    assert "judgements" in stats.to_dict()
