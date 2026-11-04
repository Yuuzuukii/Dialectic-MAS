"""MAD（Multi-Agent Debate）ベースライン（architecture.md の「比較手法」の実装）。

議論は、自由討議（free_debate.py）と同じで、発言の指示だけが「相手の直前の主張に argue against する」。
終わり方は、2通り:
- use_synthesis=False（mad）: 議論に参加しない judge が、最終回答を書く（mad_judge.py）。統合はしない。
- use_synthesis=True（mad_synthesis）: judge の代わりに、free_debate と同じ統合と最終回答。
"""

from __future__ import annotations

from typing import Any

from src.agent_migration.agents import Agent
from src.agent_migration.argumentation.dialectical import Result
from src.agent_migration.argumentation.free_debate import FreeDebate
from src.agent_migration.argumentation.mad_judge import judge_answer


class MAD(FreeDebate):
    argue_against = True

    def __init__(self, *args: Any, use_synthesis: bool = False, final_judge: Agent | None = None, **kwargs: Any):
        super().__init__(*args, **kwargs)
        if not use_synthesis and final_judge is None:
            raise ValueError("mad（judge で終わる）には、final_judge（議論に参加しない judge の Agent）が要る")
        self.use_synthesis = use_synthesis
        self.final_judge = final_judge

    async def _conclude(self, closed_by: str) -> Result:
        if self.use_synthesis:
            return await super()._conclude(closed_by)
        assert self.final_judge is not None
        self._log("judge が、議論全体から最終回答を書く（統合はしない）")
        answer = await judge_answer(self.final_judge, self.issue, self._history_json())
        return await self._finish(closed_by, answer=answer)
