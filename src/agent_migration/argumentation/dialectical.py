"""弁証的議論（architecture.md の DialecticalProtocol の実装）。

スキーマ（設計書の「スキーマ」）、プロンプト（設計書の「プロンプト構成」）、議論の進め方（設計書の「全体」の run()）。
エージェントは Agent（agents.py）。スキーマ版は agent.structured() を使う。
no schema 版は、この流れを継承して、LLM を呼ぶ部分と判定だけを差し替える（no_schema.py）。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field

from src.agent_migration.agents import Agent


# ---------------------------------------------------------------------------
# スキーマ
# ---------------------------------------------------------------------------

class Antecedent(BaseModel):
    strong_statements: list[str] = Field(
        description="The strong statements in the antecedent of the rule. "
        "Each strong statement in the antecedent of a rule is the consequent of "
        "some earlier rule. "
        "Written in a casual style: 'x is earlier than y' is our variant of the "
        "more standard logical notation Earlier(x, y)."
    )
    weak_statements: list[str] = Field(
        description="The statements in the antecedent of the rule that have weak negation, "
        "with the weak negation removed. "
        "A weak statement reads as 'there is no evidence that the statement is the case'. "
        "…a person who cannot be shown to be a minor… "
        "'If A then B, unless the contrary can be shown'… "
        "…'unless the law provides otherwise'. "
        "Written in a casual style: 'x is earlier than y' is our variant of the "
        "more standard logical notation Earlier(x, y)."
    )


class Rule(BaseModel):
    antecedent: Antecedent = Field(
        description="The conjunction at the left of the arrow. "
        "Note that a rule may have zero statements in its antecedents. "
        "Such a rule can be used to express an unconditional statement."
    )
    consequent: str = Field(
        description="The statement at the right of the arrow, "
        "written in a casual style: 'x is earlier than y' is our variant of the "
        "more standard logical notation Earlier(x, y)."
    )


class Not(BaseModel):
    negated_statement: str = Field(
        description="The statement that is negated. One of your conclusions is this very statement."
    )


class Argument(BaseModel):
    rules: list[Rule] = Field(
        description="A finite sequence of rules: a sequence of rules "
        "that can be chained together, and that is 'grounded' in the facts. "
        "When no antecedent exists in the rule we call it a fact."
    )

    def conclusions(self) -> list[str]:
        return [r.consequent for r in self.rules]

    def assumptions(self) -> list[Not]:
        # assumption = weak statement の否定（P&S 定義2.3）。Argument には持たせず、weak_statements から導く。
        return [Not(negated_statement=w) for r in self.rules for w in r.antecedent.weak_statements]

    def warrant(self) -> Rule:
        return self.rules[-1]


class Rebut(BaseModel):
    attack_type: Literal["rebut"]
    target: str = Field(
        description="One of the conclusions of the opponent's argument, which is the negation of one of your conclusions."
    )
    argument: Argument


class Undercut(BaseModel):
    attack_type: Literal["undercut"]
    target: Not = Field(
        description="One of the assumptions of the opponent's argument, which is the negation of one of your conclusions"
    )
    argument: Argument


class CannotAttack(BaseModel):
    attack_type: Literal["cannot_attack"]
    reason: str = Field(description="The reason why you cannot make an attack.")


class Attack(BaseModel):
    move: Rebut | Undercut | CannotAttack = Field(
        description="Use Rebut if your attack consists in contradicting one of the conclusions of the opponent's argument. "
        "Use Undercut if your attack consists in contradicting one of the assumptions of the opponent's argument. "
        "Use CannotAttack if you cannot make an attack."
    )


class MainArgument(BaseModel):
    argument_type: Literal["main_argument"]
    argument: Argument


class CannotArgue(BaseModel):
    argument_type: Literal["cannot_argue"]
    reason: str = Field(description="The reason why you cannot make an argument.")


class Phase1(BaseModel):
    move: MainArgument | CannotArgue


# ---------------------------------------------------------------------------
# プロンプト（設計書の「プロンプト構成」の文のまま）
# ---------------------------------------------------------------------------

ARGUMENT_FORMAT = """\
An argument is a finite sequence of rules such that:
1. For every rule in the sequence, for every strong statement in the antecedent of the rule
   there is an earlier rule in the sequence whose consequent is that strong statement.
2. For every rule in the sequence except the last, there is a later rule in the sequence
   whose antecedent has the consequent of the rule as a strong statement.
3. No two distinct rules in the sequence have the same consequent.
Condition 2 ensures that argument is a sequence of the minimum number of rules for deducing consequent of the last rule.
Further, we call the last rule a warrant of the argument.
Condition (1) says that arguments are formed by chaining rules together. A subtlety is that in doing so, weak statements may be ignored."""

PHASES = (
    "Argumentation consists of two phases. In phase 1, you and the other agent make your main arguments whose conclusions address the issue. "
    "In phase 2, you make arguments defeating the other agent's arguments. "
    "In each phase, you make arguments from your own theory. "
    "No two arguments you present have the same content. "
    "If you cannot make an argument from your own theory, you do not make one. "
    "In phase 1, if you can make no argument not yet presented, then you create new strict rules by applying the proposed reasoning method and make new main arguments based on it."
)

MAIN_ARGUMENT_USER = """\
Now it is phase 1.
Make your main argument whose conclusions address the issue.
If you cannot make a main argument, you cannot argue."""

INTEGRATE_USER = """\
Now it is phase 1.
You can make no argument not yet presented.
Create a new strict rule C from the two warrants.
Your warrant:
{mine}
The other agent's warrant:
{other}
When you face a conflict, you try to search for a solution that takes into account your intentions as much as possible and does not take into account unintentional considerations. Further, if you and the other agent show willingness to compromise, you meet each other halfway.
There are three kinds of C:
- collaboration: from C, together with your stance, both warrants follow.
- concession: from C, together with your stance, one warrant follows but the other does not.
- compromise: from C, together with your stance, neither warrant follows.
Choose the kind you can achieve, in this order: collaboration, concession, compromise."""

MAIN_ARGUMENT_FROM_RULE_USER = """\
Now it is phase 1.
You created this new strict rule by applying the proposed reasoning method:
{rule}
Make your new main argument based on it."""

ATTACK_USER = """\
Now it is phase 2.
In phase 2, you make an argument defeating the other agent's argument. If the other agent's argument does not contradict your own theory, there is nothing to defeat.
The other agent's argument:
{target}
There are two ways of attack:
- Rebut: contradicting a conclusion. One of your conclusions is the negation of one of the conclusions of the other agent's argument.
- Undercut: contradicting an assumption. An assumption of the other agent's argument is the negation of one of its weak statements. The negation of a negation is the original statement, so you contradict the assumption by deriving that weak statement itself: one of your conclusions is one of the weak statements of the other agent's argument.
If you can make neither of these attacks, you cannot attack."""

FINAL_ANSWER_USER_JUSTIFIED = (
    "Now the argumentation is over. Write your final answer to the issue in plain text. "
    "Begin with the flow of the argumentation: which opinions were put forward, which objections were raised, and how each was answered. "
    "Then give your answer to the issue."
)

FINAL_ANSWER_USER_LIMIT = (
    "Now the argumentation is over, but no argument was justified. Write your final answer to the issue in plain text. "
    "Begin with the flow of the argumentation: which opinions were put forward, which objections were raised, and how each was answered. "
    "Then state what remains undecided, and what is known."
)


# ---------------------------------------------------------------------------
# 議論の進め方
# ---------------------------------------------------------------------------

AG1, AG2 = "ag1", "ag2"

JUSTIFIED, OVERRULED, DEFENSIBLE = "justified", "overruled", "defensible"


@dataclass
class Message:
    role: str  # "ag1" | "ag2"
    content: Any  # LLM の出力（スキーマ版: スキーマのまま / no schema 版: 文章）
    kind: str  # "main" | "attack" | "integrate"
    argument: Any = None  # main / attack のときの argument

    def to_dict(self, status: str | None = None) -> dict:
        content = self.content.model_dump() if isinstance(self.content, BaseModel) else self.content
        d = {"role": self.role, "content": content}
        if status is not None:
            d["status"] = status
        return d


@dataclass
class Result:
    final_answer: str
    history: list[Message]
    statuses: dict[int, str]  # 履歴の添字 → main argument の地位
    justified_index: int | None
    turns: int
    closed_by: str  # "justified" | "turn_limit" | "no_more_arguments"
    trace: list[str] = field(default_factory=list)
    invalid_attempts: list[dict] = field(default_factory=list)  # 無効だった攻撃（履歴には入れない。分析用）


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower()).rstrip(".")


def undercuts(x: Argument, y: Argument) -> bool:
    """x が y を undercut するか（Kido 定義3）。x の結論のどれかが、y の weak statement のどれかと一致する（スキーマ版）。"""
    weak = {norm(w) for r in y.rules for w in r.antecedent.weak_statements}
    return any(norm(c) in weak for c in x.conclusions())


def other(role: str) -> str:
    return AG2 if role == AG1 else AG1


def _dump(x: Any) -> str:
    """プロンプトに入れる形。文章（no schema 版）はそのまま、スキーマの出力は JSON。"""
    if isinstance(x, str):
        return x
    return json.dumps(x.model_dump() if isinstance(x, BaseModel) else x, ensure_ascii=False, indent=2)


def _text(response: Any) -> str:
    return str(getattr(response, "content", response))


class DialecticalProtocol:
    include_format = True  # システムプロンプトに、argument の書き方指示を入れるか（no schema 版は False）

    def __init__(
        self,
        ag1: Agent,
        ag2: Agent,
        issue: str,
        theory1: str,
        theory2: str,
        max_turns: int,
    ):
        self.agents = {AG1: ag1, AG2: ag2}
        self.theory = {AG1: theory1, AG2: theory2}
        self.issue = issue
        self.max_turns = max_turns
        self.history: list[Message] = []
        self.statuses: dict[int, str] = {}
        self.turns = 0
        self.justified_index: int | None = None
        self.integrated = False
        self.trace: list[str] = []
        self.invalid_attempts: list[dict] = []

    # ---- プロンプト ----
    def _history_json(self, with_status: bool = False) -> str:
        items = [m.to_dict(self.statuses.get(i) if with_status else None) for i, m in enumerate(self.history)]
        return json.dumps(items, ensure_ascii=False, indent=2)

    def _system(self, role: str, final: bool = False) -> str:
        n, m = (1, 2) if role == AG1 else (2, 1)
        parts = [
            f"You are agent {n}. You are arguing with agent {m}.",
            f"The issue of this argumentation is:\n{self.issue}",
            f"You have these theory on the issue:\n{self.theory[role]}",
        ]
        if self.include_format and not final:
            parts.append("You speak in the form of an argument, following this format.\n" + ARGUMENT_FORMAT)
        parts.append(f"The argumentation so far:\n{self._history_json(with_status=final)}")
        if not final:
            parts.append(PHASES)
        return "\n\n".join(parts)

    # ---- エージェントの呼び出し（スキーマ版: structured）。no schema 版は、これらを差し替える ----
    async def _ask_main(self, role: str, user: str = MAIN_ARGUMENT_USER) -> tuple[Any, Any]:
        """(LLM の出力, argument)。出せないときは argument = None。"""
        move = (await self.agents[role].structured(user, Phase1, system=self._system(role))).move
        return move, (move.argument if isinstance(move, MainArgument) else None)

    async def _ask_attack(self, role: str, target: Any) -> tuple[Any, Any]:
        """(LLM の出力, argument)。攻撃できないときは argument = None。"""
        user = ATTACK_USER.replace("{target}", _dump(target))
        move = (await self.agents[role].structured(user, Attack, system=self._system(role))).move
        return move, (None if isinstance(move, CannotAttack) else move.argument)

    async def _ask_integrate(self, role: str, mine: Any, theirs: Any) -> Any:
        user = INTEGRATE_USER.replace("{mine}", _dump(mine)).replace("{other}", _dump(theirs))
        return await self.agents[role].structured(user, Rule, system=self._system(role))

    async def _ask_main_from_rule(self, role: str, rule: Any) -> tuple[Any, Any]:
        return await self._ask_main(role, MAIN_ARGUMENT_FROM_RULE_USER.replace("{rule}", _dump(rule)))

    # ---- 判定（スキーマ版: 機械的）。no schema 版は、判定用 LLM に差し替える ----
    async def _undercuts(self, x: Any, y: Any) -> bool:
        return undercuts(x, y)

    async def _rebuts(self, move: Any, a: Any, t: Any) -> bool:
        """a が t を rebut しているか。スキーマ版は、a の宣言が rebut か。"""
        return move.attack_type == "rebut"

    async def _warrant(self, argument: Any) -> Any:
        return argument.warrant()

    async def _defeats(self, a: Any, t: Any, rebut: bool) -> bool:
        return await self._undercuts(a, t) or (rebut and not await self._undercuts(t, a))

    async def _defeated_back(self, a: Any, t: Any, rebut: bool) -> bool:
        return await self._undercuts(t, a) or (rebut and not await self._undercuts(a, t))

    async def _strictly_defeats(self, a: Any, t: Any, rebut: bool) -> bool:
        return await self._defeats(a, t, rebut) and not await self._defeated_back(a, t, rebut)

    # ---- 補助 ----
    @property
    def budget_left(self) -> bool:
        return self.turns < self.max_turns

    def _record(self, role: str, content: Any, kind: str, argument: Any = None) -> int:
        self.history.append(Message(role, content, kind, argument))
        return len(self.history) - 1

    def _last_main(self, role: str) -> Any:
        for m in reversed(self.history):
            if m.role == role and m.kind == "main":
                return m.argument
        return None

    def _log(self, text: str) -> None:
        self.trace.append(text)

    # ---- phase 1 / phase 2 ----
    async def run(self) -> Result:
        turn = AG1
        failed_in_a_row = 0
        while True:
            if not self.budget_left:
                return await self._close()
            content, argument = await self._ask_main(turn)
            self.turns += 1
            if argument is None:
                self._log(f"{turn}.main_argument → できない")
                failed_in_a_row += 1
                if failed_in_a_row == 2:
                    await self._integrate(turn, evaluate=True)
                    return await self._close()
                turn = other(turn)
                continue
            failed_in_a_row = 0
            index = self._record(turn, content, "main", argument)
            self._log(f"{turn}.main_argument → main_argument（履歴 {index}）")
            status = await self._decide_status(argument, turn, main_index=index)
            self.statuses[index] = status
            self._log(f"  地位: 履歴 {index} は {status}")
            if status == JUSTIFIED:
                self.justified_index = index
                return await self._close()
            turn = other(turn)

    async def _decide_status(self, main: Any, proposer: str, used: int = 1, main_index: int | None = None) -> str:
        """used: この主張がすでに使ったターン（main_argument() の1回。統合から出した主張は 0）。"""
        opponent = other(proposer)
        chain: list[Any] = [main]
        chain_index: list[int | None] = [main_index]  # chain の各 argument の、履歴の番号
        proposer_replies = 0
        thread_limit = self.max_turns // 2  # 1つの主張が使えるターン（上限の半分）
        while True:
            mover = opponent if len(chain) % 2 == 1 else proposer
            if not self.budget_left:
                self._log("  上限到達 → defensible")
                return DEFENSIBLE
            if used >= thread_limit:
                self._log(f"  この主張の上限（{thread_limit}）に到達 → defensible")
                return DEFENSIBLE
            content, argument = await self._ask_attack(mover, chain[-1])
            self.turns += 1
            used += 1
            if argument is None:
                self._log(f"  {mover}.attack → できない（鎖の長さ {len(chain)}）")
                if mover == opponent:
                    if len(chain) == 1:
                        return JUSTIFIED
                    chain, chain_index, proposer_replies = [main], [main_index], 0  # O は M への別の攻撃を探す
                    self._log("  → O は M への別の攻撃を探す")
                    continue
                return OVERRULED if proposer_replies == 0 else DEFENSIBLE
            target = chain[-1]
            rebut = await self._rebuts(content, argument, target)
            kind = "rebut" if rebut else "undercut"
            defeat = await self._defeats(argument, target, rebut)
            if mover == proposer and defeat:
                proposer_replies += 1  # P が defeat した返答の数（相互 defeat で無効になったものも数える）
            ok = defeat if mover == opponent else (defeat and not await self._defeated_back(argument, target, rebut))
            if not ok:
                reason = "strictly defeat でない" if mover == proposer else "defeat でない"
                self._log(f"  {mover}.attack({kind}) → 無効（{reason}）")
                self.invalid_attempts.append(
                    {
                        "role": mover,
                        "declared": kind,
                        "reason": reason,
                        "target_index": chain_index[-1],
                        "main_index": main_index,
                        "content": content.model_dump() if isinstance(content, BaseModel) else content,
                    }
                )
                continue
            index = self._record(mover, content, "attack", argument)
            chain.append(argument)
            chain_index.append(index)
            self._log(f"  {mover}.attack({kind}) → 有効（履歴 {index}）")

    # ---- 統合 ----
    async def _integrate(self, integrator: str, evaluate: bool) -> None:
        self.integrated = True
        mine, theirs = self._last_main(integrator), self._last_main(other(integrator))
        if mine is None or theirs is None:
            self._log(f"統合できない（{integrator} か相手に main argument がない）")
            return
        rule = await self._ask_integrate(integrator, await self._warrant(mine), await self._warrant(theirs))
        self._record(integrator, rule, "integrate")
        self._log(f"{integrator}.integrate → rule")
        content, argument = await self._ask_main_from_rule(integrator, rule)
        if argument is None:
            self._log(f"{integrator}.main_argument_from_rule → できない")
            return
        index = self._record(integrator, content, "main", argument)
        self._log(f"{integrator}.main_argument_from_rule → main_argument（履歴 {index}）")
        if evaluate:
            status = await self._decide_status(argument, integrator, used=0, main_index=index)
            self.statuses[index] = status
            self._log(f"  地位: 履歴 {index} は {status}")
            if status == JUSTIFIED:
                self.justified_index = index

    # ---- 終了処理 ----
    async def _close(self) -> Result:
        if not self.budget_left and self.justified_index is None and not self.integrated:
            self._log("上限到達・未統合 → ag1 が統合（評価しない）")
            await self._integrate(AG1, evaluate=False)
        for i, m in enumerate(self.history):
            if m.kind == "main":
                self.statuses.setdefault(i, DEFENSIBLE)
        justified = self.justified_index is not None
        user = FINAL_ANSWER_USER_JUSTIFIED if justified else FINAL_ANSWER_USER_LIMIT
        response = await self.agents[AG1].chat(user, system=self._system(AG1, final=True))
        answer = getattr(response, "content", response)
        self._log(f"final_answer（{'justified あり' if justified else '上限・justified なし'}）")
        closed_by = "justified" if justified else ("turn_limit" if not self.budget_left else "no_more_arguments")
        return Result(
            answer, self.history, self.statuses, self.justified_index, self.turns, closed_by, self.trace, self.invalid_attempts
        )
