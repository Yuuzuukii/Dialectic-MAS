"""no schema 版（architecture.md の「no schema 版」の実装）。

流れ（DialecticalProtocol）と、各行動のユーザープロンプトは、スキーマ版と同じ。
スキーマ（structured output）と、argument の書き方指示だけを抜く。
エージェントの出力は文章（agent.chat()）。流れが必要とする判定は、判定用の Agent にさせる。
"""

from __future__ import annotations

from typing import Any

from src.agent_migration.agents import Agent
from src.agent_migration.argumentation.dialectical import (
    ATTACK_USER,
    INTEGRATE_USER,
    MAIN_ARGUMENT_USER,
    DialecticalProtocol,
    _dump,
    _text,
)

# 判定用プロンプト（設計書の「no schema 版」の文のまま）
CANNOT_JUDGE = """\
The following is an agent's reply.
{reply}
Does the reply say that the agent cannot do it? Answer yes or no."""

UNDERCUTS_JUDGE = """\
Argument X:
{x}

Argument Y:
{y}

Does X undercut Y? X undercuts Y if one of the conclusions of X contradicts an assumption of Y, that is, a statement that Y takes to hold only because there is no evidence to the contrary. Answer yes or no."""

CLASSIFY_ATTACK = """\
Argument X:
{x}

Argument Y:
{y}

The agent stated X to attack Y. Does X attack Y by rebutting it or by undercutting it? X rebuts Y if one of the conclusions of X is the negation of one of the conclusions of Y. X undercuts Y if one of the conclusions of X contradicts an assumption of Y, that is, a statement that Y takes to hold only because there is no evidence to the contrary. Answer rebut or undercut."""

WARRANT_EXTRACT = """\
Argument:
{argument}

Write the warrant of this argument: the last step, which states what the argument finally concludes, together with what that conclusion is based on. Copy it as it is stated."""


class NoSchemaProtocol(DialecticalProtocol):
    include_format = False

    def __init__(self, *args: Any, judge: Agent, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.judge = judge  # 判定用。システムプロンプトは付けない。ターンには数えない。

    async def _judge_yes(self, prompt: str) -> bool:
        """判定用 Agent の答えを、先頭の単語で読む（yes なら True）。"""
        words = _text(await self.judge.chat(prompt)).strip().lower().split()
        return bool(words) and words[0].strip(".,!:;\"'") == "yes"

    async def _ask_free(self, role: str, user: str) -> tuple[str, str | None]:
        """(文章, argument)。できないと言っているときは argument = None。argument は、文章そのもの。"""
        reply = _text(await self.agents[role].chat(user, system=self._system(role)))
        cannot = await self._judge_yes(CANNOT_JUDGE.replace("{reply}", reply))
        return reply, (None if cannot else reply)

    async def _ask_main(self, role: str, user: str = MAIN_ARGUMENT_USER) -> tuple[Any, Any]:
        return await self._ask_free(role, user)

    async def _ask_attack(self, role: str, target: Any) -> tuple[Any, Any]:
        return await self._ask_free(role, ATTACK_USER.replace("{target}", _dump(target)))

    async def _ask_integrate(self, role: str, mine: Any, theirs: Any) -> Any:
        user = INTEGRATE_USER.replace("{mine}", _dump(mine)).replace("{other}", _dump(theirs))
        return _text(await self.agents[role].chat(user, system=self._system(role)))

    # _ask_main_from_rule は、基底クラスのまま（_ask_main に、文章の rule を入れる）

    async def _undercuts(self, x: Any, y: Any) -> bool:
        return await self._judge_yes(UNDERCUTS_JUDGE.replace("{x}", x).replace("{y}", y))

    async def _rebuts(self, move: Any, a: Any, t: Any) -> bool:
        """宣言の代わりに、判定用 LLM が、攻撃の種類（rebut / undercut）だけを読み取る。成立の判定はしない。
        あとの defeat の決め方は、スキーマ版と同じ（undercut なら defeat、rebut なら、既出の相手が undercut し返せるかだけを見る）。"""
        words = _text(await self.judge.chat(CLASSIFY_ATTACK.replace("{x}", a).replace("{y}", t))).strip().lower().split()
        return not (words and words[0].strip(".,!:;\"'") == "undercut")

    async def _warrant(self, argument: Any) -> Any:
        return _text(await self.judge.chat(WARRANT_EXTRACT.replace("{argument}", argument)))
