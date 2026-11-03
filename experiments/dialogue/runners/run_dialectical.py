"""新しい弁証的議論（src/agent_migration）の実験ランナー。

対象: トピック JSON 1つ / カテゴリ（datasets/ 配下のフォルダ名）/ all（全トピック）。
手法: schema（スキーマ出力）/ no_schema（スキーマ出力なし。判定用 LLM を使う）。
ログは、実行開始時刻の experiment_<日時> の下に、ターン数ごとに分けて保存する。
  <output-root>/turns<N>/raw_dialogue/<カテゴリ>/<トピック>/[NN_]<method>_<日時>.json
  （NN は --runs が 2 以上のときの run 番号。ファイル名は common.output_path に任せる）

使い方（リポジトリのルートで。LLM API の費用がかかるので、実行は自分で行う）:
    .venv/bin/python -m experiments.dialogue.runners.run_dialectical schema datasets/Education/free_college.json --turns 10
    .venv/bin/python -m experiments.dialogue.runners.run_dialectical no_schema Education --turns 10 20 30 --runs 3
    .venv/bin/python -m experiments.dialogue.runners.run_dialectical schema all --turns 10 --dry-run   # 費用なし。計画だけ表示
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
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
from src.agent_migration.argumentation.dialectical import DialecticalProtocol  # noqa: E402
from src.agent_migration.argumentation.no_schema import NoSchemaProtocol  # noqa: E402


def resolve_topics(target: str) -> list[Path]:
    if target == "all":
        return all_topic_files()
    path = Path(target)
    if not path.is_absolute():
        path = ROOT / path
    if path.is_file():
        return [path]
    return category_topic_files(target)


def build_agents(model: str | None, judge_model: str | None) -> tuple[Agent, Agent, Agent, dict[str, TokenUsageTracker]]:
    """(ag1, ag2, judge, トークン集計)。ag1 と ag2 は、同じクライアント（同じモデル）を共有する。"""
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
    return (
        Agent(client=client, system_prompt=""),
        Agent(client=client, system_prompt=""),
        Agent(client=judge_client, system_prompt=""),
        trackers,
    )


def make_protocol(method: str, topic: dict[str, Any], max_turns: int, ag1: Agent, ag2: Agent, judge: Agent):
    kwargs: dict[str, Any] = dict(
        issue=topic["question"],
        theory1=topic["agent1_stance"],
        theory2=topic["agent2_stance"],
        max_turns=max_turns,
    )
    if method == "no_schema":
        return NoSchemaProtocol(ag1, ag2, judge=judge, **kwargs)
    return DialecticalProtocol(ag1, ag2, **kwargs)


def usage_summary(trackers: dict[str, TokenUsageTracker]) -> dict[str, Any]:
    usage = {name: t.usage() for name, t in trackers.items()}
    usage["total_cost_usd"] = round(sum(u["total_cost_usd"] for u in usage.values()), 6)
    return usage


async def run_one(
    method: str,
    topic_file: Path,
    max_turns: int,
    output_root: Path,
    run_index: int | None,
    ag1: Agent,
    ag2: Agent,
    judge: Agent,
    trackers: dict[str, TokenUsageTracker],
) -> Path:
    """1トピック・1回の議論を行い、ログを保存する。途中で例外が出ても、そこまでの履歴を保存する。"""
    topic_path, topic = load_topic(topic_file)
    protocol = make_protocol(method, topic, max_turns, ag1, ag2, judge)
    before = usage_summary(trackers)["total_cost_usd"]
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
    usage = usage_summary(trackers)
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
            # トークン数は、実行全体の累計。この回の費用は、実行前との差。
            "usage_cumulative": usage,
            "cost_usd_this_run": round(usage["total_cost_usd"] - before, 6),
        },
        "dialogue_history": [m.to_dict(statuses.get(i)) for i, m in enumerate(protocol.history)],
        "statuses": {str(i): s for i, s in statuses.items()},
        "final_answer": result.final_answer if result else None,
        "trace": protocol.trace,
        # 無効だった攻撃（履歴には入れていない。分析用）
        "invalid_attempts": protocol.invalid_attempts,
    }
    if error is not None:
        log["error"] = error
    path = save_log(log, output_path(method, topic_path, output_root / f"turns{max_turns}" / "raw_dialogue", run_index))  # type: ignore[arg-type]
    print(f"[system] log saved -> {path}", flush=True)  # noqa: T201
    return path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the new dialectical argumentation (src/agent_migration).")
    parser.add_argument("method", choices=["schema", "no_schema"])
    parser.add_argument("target", help="トピック JSON のパス / カテゴリ名 / all")
    parser.add_argument("--turns", type=int, nargs="+", default=[10], help="max_dialogue_turns（複数指定可。ターン数ごとに turns<N>/ に保存）")
    parser.add_argument("--runs", type=int, default=1, help="トピックごとの実行回数")
    parser.add_argument("--output-root", type=Path, default=None, help="既定: logs/experiment_<開始時刻>")
    parser.add_argument("--model", default=None, help="エージェントのモデル（既定: config.py の DIALOGUE_AGENT_MODEL）")
    parser.add_argument("--judge-model", default=None, help="判定用のモデル（既定: config.py の JUDGE_MODEL。no_schema のみ使う）")
    parser.add_argument("--dry-run", action="store_true", help="LLM を呼ばず、計画だけ表示する（費用なし）")
    parser.add_argument("--fail-fast", action="store_true", help="最初の失敗で止める")
    return parser.parse_args(argv)


async def main(argv: list[str] | None = None) -> list[Path]:
    args = parse_args(argv)
    topics = resolve_topics(args.target)
    if not topics:
        raise FileNotFoundError(f"トピックが見つからない: {args.target}")
    root = args.output_root or LOGS_DIR / f"experiment_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    total = len(topics) * len(args.turns) * args.runs
    print(f"[plan] method={args.method} topics={len(topics)} turns={args.turns} runs={args.runs} → {total} 回", flush=True)  # noqa: T201
    print(f"[plan] 保存先: {root}/turns<N>/raw_dialogue/<カテゴリ>/<トピック>/", flush=True)  # noqa: T201
    if args.dry_run:
        for t in topics[:5]:
            print(f"[plan]   {t.parent.name}/{t.stem}", flush=True)  # noqa: T201
        if len(topics) > 5:
            print(f"[plan]   … ほか {len(topics) - 5} 件", flush=True)  # noqa: T201
        return []
    ag1, ag2, judge, trackers = build_agents(args.model, args.judge_model)
    saved: list[Path] = []
    for max_turns in args.turns:
        for topic_file in topics:
            print(f"=== [{args.method}][turns{max_turns}][{topic_file.parent.name}] {topic_file.stem} ===", flush=True)  # noqa: T201
            for index in range(1, args.runs + 1):
                try:
                    saved.append(
                        await run_one(args.method, topic_file, max_turns, root, index if args.runs > 1 else None, ag1, ag2, judge, trackers)
                    )
                except Exception as exc:  # noqa: BLE001
                    print(f"[error] {topic_file}: {exc}", file=sys.stderr, flush=True)  # noqa: T201
                    if args.fail_fast:
                        raise
    print(f"[done] 累計費用の見積もり: ${usage_summary(trackers)['total_cost_usd']}", flush=True)  # noqa: T201
    return saved


if __name__ == "__main__":
    asyncio.run(main())
