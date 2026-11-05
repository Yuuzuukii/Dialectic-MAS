"""新しい弁証的議論（src/agent_migration）と、比較手法の実験ランナー。

手法: schema / no_schema / free_debate / mad / mad_synthesis（`--methods` に、`,` 区切りで）。
対象: トピック JSON（複数可）/ カテゴリ名（datasets/ 配下のフォルダ）/ all（全トピック）。
ログは、実行開始時刻の experiment_<日時> の下に、ターン数ごとに分けて保存する。
  <experiment-dir>/turns<N>/raw_dialogue/<カテゴリ>/<トピック>/[NN_]<method>_<日時>.json
  （NN は --runs が 2 以上のときの run 番号。ファイル名は common.output_path に任せる）

使い方（リポジトリのルートで。LLM API の費用がかかるので、実行は自分で行う）:
    MODEL=... .venv/bin/python -m experiments.dialogue.runners.run_dialectical \\
      datasets/Education/animal_dissection.json --methods schema,no_schema --turns 10
    .venv/bin/python -m experiments.dialogue.runners.run_dialectical Education --methods free_debate,mad,mad_synthesis \\
      --turns 10 15 20 --runs 3 --concurrency 8 --dry-run     # 費用なし。計画だけ表示
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.dialogue.common import (  # noqa: E402
    LOGS_DIR,
    TokenUsageTracker,
    all_topic_files,
    category_topic_files,
    load_topic,
    output_path,
    save_log,
)
from src.agent_migration.agents import Agent  # noqa: E402
from src.agent_migration.argumentation.dialectical import Argument, DialecticalProtocol, Message  # noqa: E402
from src.agent_migration.argumentation.free_debate import FreeDebate  # noqa: E402
from src.agent_migration.argumentation.mad import MAD  # noqa: E402
from src.agent_migration.argumentation.no_schema import NoSchemaProtocol  # noqa: E402

METHODS = ("schema", "no_schema", "free_debate", "mad", "mad_synthesis")


@dataclass
class Agents:
    """1回の実行で使う Agent。ag1 と ag2 と final_judge は、議論の書き手と同じクライアント（同じモデル）。"""

    ag1: Agent
    ag2: Agent
    helper: Agent  # 判定用（no_schema、free_debate、mad_synthesis の、統合と最終回答の補助。別のモデル）
    final_judge: Agent  # mad の judge（議論の書き手と同じモデル。既存と同じ）
    trackers: dict[str, TokenUsageTracker]


def resolve_topics(target: str) -> list[Path]:
    if target == "all":
        return all_topic_files()
    path = Path(target)
    if not path.is_absolute():
        path = ROOT / path
    if path.is_file():
        return [path]
    return category_topic_files(target)


def build_agents(model: str | None, judge_model: str | None) -> Agents:
    """1回の実行ぶんの Agent を作る（費用を、実行ごとに、正確に数えるため、実行ごとに作る）。"""
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
    except ImportError:  # pragma: no cover
        pass
    from src.agent_migration.client.llm import OpenAIClient
    from src.agent_migration.config import DIALOGUE_AGENT_MODEL, JUDGE_MODEL, OPENAI_API_KEY

    model = model or DIALOGUE_AGENT_MODEL
    judge_model = judge_model or JUDGE_MODEL
    trackers = {"agents": TokenUsageTracker(model), "judge": TokenUsageTracker(judge_model)}
    client = OpenAIClient(model=model, api_key=OPENAI_API_KEY, callbacks=[trackers["agents"]])
    judge_client = OpenAIClient(model=judge_model, api_key=OPENAI_API_KEY, callbacks=[trackers["judge"]])
    return Agents(
        ag1=Agent(client=client, system_prompt=""),
        ag2=Agent(client=client, system_prompt=""),
        helper=Agent(client=judge_client, system_prompt=""),
        final_judge=Agent(client=client, system_prompt=""),
        trackers=trackers,
    )


def make_protocol(method: str, topic: dict[str, Any], max_turns: int, agents: Agents) -> DialecticalProtocol:
    kwargs: dict[str, Any] = dict(
        issue=topic["question"],
        theory1=topic["agent1_stance"],
        theory2=topic["agent2_stance"],
        max_turns=max_turns,
    )
    if method == "schema":
        return DialecticalProtocol(agents.ag1, agents.ag2, **kwargs)
    if method == "no_schema":
        return NoSchemaProtocol(agents.ag1, agents.ag2, judge=agents.helper, **kwargs)
    if method == "free_debate":
        return FreeDebate(agents.ag1, agents.ag2, judge=agents.helper, **kwargs)
    if method == "mad":
        return MAD(agents.ag1, agents.ag2, judge=agents.helper, use_synthesis=False, final_judge=agents.final_judge, **kwargs)
    if method == "mad_synthesis":
        return MAD(agents.ag1, agents.ag2, judge=agents.helper, use_synthesis=True, **kwargs)
    raise ValueError(f"未知の手法: {method}")


def legacy_argument(argument: Any) -> Any:
    """発言の argument を、既存の評価スクリプトが読む形にする（schema は rules の JSON、自由文は、そのまま）。"""
    if isinstance(argument, Argument):
        rules = [
            {
                "antecedent": {"strong": list(r.antecedent.strong_statements), "weak_negation": list(r.antecedent.weak_statements)},
                "consequent": r.consequent,
            }
            for r in argument.rules
        ]
        weak = [w for r in argument.rules for w in r.antecedent.weak_statements]
        return {"Argument": {"rules": rules, "Conc": argument.conclusions(), "Ass": weak}}
    return argument


def legacy_dialogue_history(history: list[Message], statuses: dict[int, str]) -> list[dict[str, Any]]:
    """履歴を、既存の評価スクリプトが読む形（agent / type / argument / attack / target_id / status）にする。

    議論の発言（main、攻撃、比較手法の発言）だけを入れる。統合の rule は、入れない（統合から出た主張は、main として入る）。
    比較手法（free_debate / mad）の発言は、type を持たない（既存と同じ）。
    """
    out: list[dict[str, Any]] = []
    for i, m in enumerate(history):
        if m.kind == "integrate":
            continue
        entry: dict[str, Any] = {"id": f"h{i}", "agent": m.role.upper(), "argument": legacy_argument(m.argument)}
        if m.kind in ("main", "attack"):
            entry["type"] = m.phase
            entry["proponent"] = (m.proponent or m.role).upper()
        if m.kind == "attack":
            entry["attack"] = m.attack
            entry["target_id"] = f"h{m.target_index}"
            if m.target_statement is not None:
                entry["target_statement"] = m.target_statement
        if m.kind == "main" and i in statuses:
            entry["status"] = statuses[i]
        out.append(entry)
    return out


def usage_summary(trackers: dict[str, TokenUsageTracker]) -> dict[str, Any]:
    usage: dict[str, Any] = {name: t.usage() for name, t in trackers.items()}
    usage["total_cost_usd"] = round(sum(u["total_cost_usd"] for u in usage.values()), 6)
    return usage


async def run_one(
    method: str,
    topic_file: Path,
    max_turns: int,
    output_root: Path,
    run_index: int | None,
    agents: Agents,
) -> Path:
    """1トピック・1回の議論を行い、ログを保存する。途中で例外が出ても、そこまでの履歴を保存する。"""
    topic_path, topic = load_topic(topic_file)
    protocol = make_protocol(method, topic, max_turns, agents)
    start = time.perf_counter()
    error: str | None = None
    result = None
    try:
        result = await protocol.run()
    except Exception as exc:  # noqa: BLE001 - 途中までの履歴を残すため
        error = f"{type(exc).__name__}: {exc}"
        print(f"[error] {topic_path}: {error}", file=sys.stderr, flush=True)
    elapsed = time.perf_counter() - start
    statuses = result.statuses if result else protocol.statuses
    usage = usage_summary(agents.trackers)
    log: dict[str, Any] = {
        "method": method,
        "question": topic["question"],
        "agent1_stance": topic["agent1_stance"],
        "agent2_stance": topic["agent2_stance"],
        "metrics": {
            "elapsed_seconds": round(elapsed, 3),
            "max_dialogue_turns": max_turns,
            "turns": protocol.turns,
            "closed_by": result.closed_by if result else None,
            "justified_index": protocol.justified_index,
            "total_dialogue_turns": protocol.turns,
            "main_argument_count": sum(1 for m in protocol.history if m.kind == "main"),
            "attack_turn_count": sum(1 for m in protocol.history if m.kind == "attack"),
            "overruled_count": sum(1 for s in statuses.values() if s == "overruled"),
            "defensible_count": sum(1 for s in statuses.values() if s == "defensible"),
            "justified_proven_count": sum(1 for s in statuses.values() if s == "justified"),
            "usage": usage,  # この回の、トークン数と費用（エージェントと判定用に分けた）
            "cost_usd_this_run": usage["total_cost_usd"],
        },
        # 既存の評価スクリプトが読む形（議論の発言だけ。統合の rule は、入れない）
        "dialogue_history": legacy_dialogue_history(protocol.history, statuses),
        # この実装の履歴そのもの（role / content / kind。統合の rule も含む）
        "history": [{**m.to_dict(statuses.get(i)), "kind": m.kind} for i, m in enumerate(protocol.history)],
        "statuses": {str(i): s for i, s in statuses.items()},
        "integrated_rules": [],  # 統合から出た主張は、dialogue_history の main として入っている
        "consensus_reached": protocol.justified_index is not None,
        "justification_status": "justified" if protocol.justified_index is not None else "fallback_no_consensus",
        "final_answer": result.final_answer if result else None,
        "trace": protocol.trace,
        # 無効だった攻撃（履歴には入れていない。分析用。schema / no_schema のみ）
        "invalid_attempts": protocol.invalid_attempts,
    }
    if error is not None:
        log["error"] = error
    path = save_log(log, output_path(method, topic_path, output_root / f"turns{max_turns}" / "raw_dialogue", run_index))  # type: ignore[arg-type]
    print(f"[system] log saved -> {path}", flush=True)  # noqa: T201
    return path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the new dialectical argumentation and the baselines (src/agent_migration).")
    parser.add_argument("targets", nargs="+", help="トピック JSON のパス（複数可）/ カテゴリ名 / all")
    parser.add_argument("--methods", default="schema,no_schema", help=f"',' 区切り（{' / '.join(METHODS)}）")
    parser.add_argument("--turns", type=int, nargs="+", default=[10], help="max_dialogue_turns（複数指定可。ターン数ごとに turns<N>/ に保存）")
    parser.add_argument("--runs", type=int, default=1, help="条件ごとの実行回数")
    parser.add_argument("--run-start", type=int, default=1, help="run 番号の開始値（欠けた run だけを足すとき用）")
    parser.add_argument("--experiment-dir", type=Path, default=None, help="既存の実験フォルダに追加で保存する。未指定なら logs/experiment_<開始時刻> を新しく作る")
    parser.add_argument("--concurrency", type=int, default=8, help="同時に実行する run 数の上限（API のレート制限対策）")
    parser.add_argument("--model", default=None, help="エージェントのモデル（既定: config.py の DIALOGUE_AGENT_MODEL）")
    parser.add_argument("--judge-model", default=None, help="判定用のモデル（既定: config.py の JUDGE_MODEL）")
    parser.add_argument("--dry-run", action="store_true", help="LLM を呼ばず、計画だけ表示する（費用なし）")
    return parser.parse_args(argv)


async def main(argv: list[str] | None = None) -> list[Path]:
    args = parse_args(argv)
    methods = [m.strip() for m in args.methods.split(",") if m.strip()]
    unknown = [m for m in methods if m not in METHODS]
    if unknown:
        raise SystemExit(f"未知の手法: {unknown}（{', '.join(METHODS)}）")
    topics: list[Path] = []
    for target in args.targets:
        for topic in resolve_topics(target):
            if topic not in topics:
                topics.append(topic)
    if not topics:
        raise FileNotFoundError(f"トピックが見つからない: {args.targets}")
    root = args.experiment_dir or LOGS_DIR / f"experiment_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    jobs = [
        (method, topic, turns, index)
        for turns in args.turns
        for topic in topics
        for method in methods
        for index in range(args.run_start, args.run_start + args.runs)
    ]
    print(f"[plan] methods={methods} topics={len(topics)} turns={args.turns} runs={args.runs} → {len(jobs)} 回（同時 {args.concurrency}）", flush=True)  # noqa: T201
    print(f"[plan] 保存先: {root}/turns<N>/raw_dialogue/<カテゴリ>/<トピック>/", flush=True)  # noqa: T201
    if args.dry_run:
        for t in topics[:5]:
            print(f"[plan]   {t.parent.name}/{t.stem}", flush=True)  # noqa: T201
        if len(topics) > 5:
            print(f"[plan]   … ほか {len(topics) - 5} 件", flush=True)  # noqa: T201
        return []
    semaphore = asyncio.Semaphore(max(1, args.concurrency))

    async def limited(method: str, topic: Path, turns: int, index: int) -> Path:
        async with semaphore:
            agents = build_agents(args.model, args.judge_model)
            return await run_one(method, topic, turns, root, index if args.runs > 1 else None, agents)

    results = await asyncio.gather(*(limited(*job) for job in jobs), return_exceptions=True)
    saved = [r for r in results if isinstance(r, Path)]
    failed = [r for r in results if not isinstance(r, Path)]
    print(f"[done] 保存 {len(saved)} / {len(jobs)} 本、失敗 {len(failed)} 本", flush=True)  # noqa: T201
    for exc in failed:
        print(f"[error] {exc}", file=sys.stderr, flush=True)  # noqa: T201
    return saved


if __name__ == "__main__":
    asyncio.run(main())
