"""1 回の議論（run）の、判定の呼び出しと、書き直しの回数を数える.

議論は、複数の run を同時に走らせる（asyncio のタスクごと）ので、集計は、コンテキスト変数で、
run ごとに分ける。run の開始時に ``begin_run`` を呼ぶと、その run の中（子のタスクを含む）の
``record_*`` が、同じ集計に入る。開始されていなければ、何も記録しない（テストなど）。
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

_TOKEN_KEYS = ("prompt_tokens", "cached_tokens", "completion_tokens", "total_tokens")


@dataclass
class RunStats:
    """1 回の run の集計（判定の呼び出し回数とトークン数、書き直しの回数）."""

    judge_calls: dict[str, int] = field(default_factory=dict)
    judge_tokens: dict[str, int] = field(default_factory=lambda: dict.fromkeys(_TOKEN_KEYS, 0))
    regenerations: dict[str, int] = field(default_factory=dict)
    # 判定の 1 回ごとの、入力の要点、結果、判定者の理由（後から、判定の妥当性を読んで確かめるため）。
    judgements: list[dict[str, Any]] = field(default_factory=list)
    # 形式の違反で却下された下書き（書き直しで捨てられたもの）。本文と、違反の理由を残す。
    discarded_drafts: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """ログに保存する形にする."""
        return {
            "judge_calls": dict(self.judge_calls),
            "judge_tokens": dict(self.judge_tokens),
            "regenerations": dict(self.regenerations),
            "judgements": [dict(item) for item in self.judgements],
            "discarded_drafts": [dict(item) for item in self.discarded_drafts],
        }


_current: ContextVar[RunStats | None] = ContextVar("run_stats", default=None)


def begin_run() -> RunStats:
    """この run の集計を始め、現在のコンテキストに結びつける."""
    stats = RunStats()
    _current.set(stats)
    return stats


def usage_tokens(usage_metadata: dict[str, Any]) -> dict[str, int]:
    """LangChain の usage_metadata（モデル名ごと）を、プロンプト、キャッシュ、出力、合計に足し合わせる."""
    total = dict.fromkeys(_TOKEN_KEYS, 0)
    for entry in (usage_metadata or {}).values():
        details = entry.get("input_token_details") or {}
        total["prompt_tokens"] += int(entry.get("input_tokens", 0))
        total["cached_tokens"] += int(details.get("cache_read", 0))
        total["completion_tokens"] += int(entry.get("output_tokens", 0))
        total["total_tokens"] += int(entry.get("total_tokens", 0))
    return total


def record_judge(kind: str, usage_metadata: dict[str, Any]) -> None:
    """判定の呼び出し 1 回（kind は rebut / undercut / extract）と、そのトークン数を記録する."""
    stats = _current.get()
    if stats is None:
        return
    stats.judge_calls[kind] = stats.judge_calls.get(kind, 0) + 1
    for key, value in usage_tokens(usage_metadata).items():
        stats.judge_tokens[key] += value


def record_regeneration(kind: str) -> None:
    """形式の違反による、書き直し 1 回を記録する（kind は main / attack。出せなかったときは ..._gave_up）."""
    stats = _current.get()
    if stats is None:
        return
    stats.regenerations[kind] = stats.regenerations.get(kind, 0) + 1


def record_judgement(entry: dict[str, Any]) -> None:
    """判定 1 回の、入力の要点、結果、判定者の理由を記録する."""
    stats = _current.get()
    if stats is None:
        return
    stats.judgements.append(entry)


def record_discarded(entry: dict[str, Any]) -> None:
    """形式の違反で却下された下書き 1 件（本文、違反の理由、どの手のものか）を記録する."""
    stats = _current.get()
    if stats is None:
        return
    stats.discarded_drafts.append(entry)
