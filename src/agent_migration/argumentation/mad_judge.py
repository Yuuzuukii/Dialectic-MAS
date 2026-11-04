"""MAD の judge（architecture.md の「比較手法」の実装）。

議論に参加しない judge が、議論全体から、勝者を決めて、最終回答を書く（既存実装の MAD_JUDGE の文のまま）。
統合はしない。judge は、議論の書き手と同じモデルの Agent を渡す（既存と同じ）。
"""

from __future__ import annotations

from src.agent_migration.agents import Agent
from src.agent_migration.argumentation.dialectical import _text

MAD_JUDGE_SYSTEM = (
    "<role>\nYou are an independent judge. You did not participate in this debate.\n</role>\n\n"
    "<task>\nBased on the debate so far, select a single winner and formulate the final answer based on his opinion. "
    "however, there is no need to announce the winner within the text of the answer itself.\n</task>"
)

MAD_JUDGE_USER = """\
Question: {question}

Dialogue history:
{dialogue_history}"""


async def judge_answer(judge: Agent, question: str, dialogue_history: str) -> str:
    """議論全体（履歴の JSON）から、最終回答を書く。"""
    user = MAD_JUDGE_USER.replace("{question}", question).replace("{dialogue_history}", dialogue_history)
    return _text(await judge.chat(user, system=MAD_JUDGE_SYSTEM)).strip()
