"""自由討議ベースライン（architecture.md の「比較手法」の実装）。

議論は、ag1 → ag2 の順に、交代で発言するだけ（既存実装 src/agent/free_debate.py と同じ）。
統合と最終回答は、no schema 版と同じもの（NoSchemaProtocol を継承して使う）。
MAD（mad.py）は、この議論の指示を「相手に argue against する」に変えたもの。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from src.agent_migration.argumentation.dialectical import AG1, AG2, Result, other
from src.agent_migration.argumentation.no_schema import NoSchemaProtocol


class DebateTurn(BaseModel):
    """1 ターン分の発話と、新しい論点を出せたかの自己申告フラグ."""

    argument: str = Field(description="Your argument for your stance this turn.")
    has_new_point: bool = Field(
        description=(
            "True if this turn introduces a genuinely new argument or rebuttal not already "
            "made earlier in the debate. False if you have nothing substantively new to add "
            "beyond what has already been said."
        )
    )


# 既存実装（src/agent/prompts.py の _GROUNDING）の文のまま。
GROUNDING = """\
<grounding>
- Your values, priorities, and the position you argue for come from your stance; never contradict your stance or adopt priorities it does not contain.
- Where your stance, the target argument, the dialogue history, or the integrated rules already provide the facts or rules that settle a point, argue from those; do not override or replace them with outside knowledge.
- Where they are silent, you may draw on general knowledge — facts, examples, analogies, mechanisms — to support your position or to challenge the other side's reasoning.
</grounding>"""

# 2ラウンド目以降の指示に付ける、新規性の逃げ道（既存実装の文のまま）。
NOVELTY_HINT = (
    " Before answering, compare what you plan to say against everything your side has already"
    " said earlier in this debate (earlier arguments and rebuttals alike). If the only thing you"
    " can say substantially restates it — the same facts or reasoning, even if reworded or"
    " reframed — do not resubmit it: say briefly that you have nothing new and set"
    " has_new_point=false. Otherwise, make your new argument or rebuttal and set"
    " has_new_point=true."
)


class FreeDebate(NoSchemaProtocol):
    """自由討議。統合と最終回答は、no schema 版と同じ（判定用 Agent を使う）。"""

    argue_against = False  # MAD は True

    # ---- プロンプト ----
    def _debate_system(self, role: str) -> str:
        n, m = (1, 2) if role == AG1 else (2, 1)
        return "\n\n".join(
            [
                "<identity>\n"
                f'You are agent {n} in this debate. In the debate so far, turns whose role is "{role}" '
                f"are your own past turns; agent {m} is your opponent.\n"
                "</identity>",
                self.theory[role],
                GROUNDING,
                f"The debate so far:\n{self._history_json()}",
            ]
        )

    def _round_instruction(self, role: str, round_no: int) -> str:
        if round_no == 1:
            if role == AG1:
                return f"Question: {self.issue}\n\nState your initial argument for your stance."
            if self.argue_against:
                return "Considering agent 1's argument in the debate so far, argue against it and state your argument for your stance."
            return "Considering agent 1's argument in the debate so far, state your initial argument for your stance."
        rival = 2 if role == AG1 else 1
        if self.argue_against:
            return (
                f"Considering agent {rival}'s latest argument in the debate so far, argue against it and give your updated"
                " argument for your stance." + NOVELTY_HINT
            )
        if role == AG1:
            return (
                "Considering the debate so far, give your updated argument for your stance."
                + NOVELTY_HINT
            )
        return (
            "Considering the debate so far, including agent 1's latest argument, give your updated"
            " argument for your stance." + NOVELTY_HINT
        )

    async def _debate_turn(self, role: str, round_no: int) -> DebateTurn:
        turn = await self.agents[role].structured(
            self._round_instruction(role, round_no), DebateTurn, system=self._debate_system(role)
        )
        assert isinstance(turn, DebateTurn)
        return turn

    # ---- 終わり方（MAD は、judge に差し替える） ----
    async def _conclude(self, closed_by: str) -> Result:
        """各陣営の最後の発言から、今の統合（評価しない）をして、今の最終回答を書く。"""
        self._log("統合（各陣営の最後の発言から。評価しない）")
        await self._integrate(AG1, evaluate=False)
        return await self._finish(closed_by)

    # ---- 議論 ----
    async def run(self) -> Result:
        role, round_no = AG1, 1
        has_new: dict[str, bool] = {}
        closed_by = "turn_limit"
        while self.budget_left:
            turn = await self._debate_turn(role, round_no)
            self.turns += 1
            text = turn.argument.strip()
            has_new[role] = True if round_no == 1 else turn.has_new_point  # 1ラウンド目は、定義上、新しい
            index = self._record(role, text, "turn", text)
            self._log(f"{role}.turn（ラウンド {round_no}、履歴 {index}、新しい論点: {has_new[role]}）")
            if role == AG2:
                if has_new.get(AG1) is False and has_new.get(AG2) is False:
                    closed_by = "no_new_point"
                    self._log("両者とも新しい論点なし → 終了")
                    break
                round_no += 1
            role = other(role)
        return await self._conclude(closed_by)
