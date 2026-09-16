"""議論状態に保持するレコード型（ArgumentRecord / DefeatRelation）とその補助関数."""

from __future__ import annotations

import json
from typing import Any, Literal, Self
from uuid import uuid4

from pydantic import BaseModel, Field

from .types import AgentName, ArgumentStatus, ArgumentType, AttackType


def parse_serialized_payload(text: str | None) -> dict[str, Any]:
    """LLM 出力テキスト（コードフェンス等を含みうる）から JSON dict を抽出する."""
    if not text:
        return {}
    try:
        if "```json" in text:
            start = text.find("```json") + len("```json")
            text = text[start : text.find("```", start)].strip()
        elif "```" in text:
            start = text.find("```") + len("```")
            text = text[start : text.find("```", start)].strip()
        else:
            text = text[text.find("{") : text.rfind("}") + 1].strip()
        value = json.loads(text)
        return value if isinstance(value, dict) else {}
    except (AttributeError, TypeError, json.JSONDecodeError):
        return {}


def _text_items(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


# ログ
class ArgumentRecord(BaseModel):
    """議論履歴に積む 1 発言（主張・攻撃・防御）のレコード."""

    id: str = Field(
        default_factory=lambda: f"arg-{uuid4().hex[:10]}",
        description="Internal argument id.",
    )
    type: ArgumentType = Field(
        description="main for an initial claim, defeat for an opponent attack, counter for a defense."
    )
    argument: str = Field(description="Serialized argument payload.")
    support: list[str] = Field(
        default_factory=list, description="Optional supporting facts or references."
    )
    agent: AgentName = Field(description="Agent that produced this argument.")
    proponent: AgentName | None = Field(
        default=None,
        description=(
            "このレコードが生成された時点で state.current_proponent だった agent。"
            "main/counter は本人と一致するが、defeat（相手からの攻撃）はここが "
            "author（agent）と異なる。dialogue turn 予算を proponent 別に按分する際に使う。"
        ),
    )
    target_id: str | None = Field(
        default=None, description="Argument id targeted by this defeating argument."
    )
    attack: AttackType | None = Field(
        default=None, description="Attack type: rebut or undercut."
    )
    target_field: Literal["Conc", "Ass"] | None = Field(
        default=None,
        description="Field in the targeted argument attacked by this argument.",
    )
    target_statement: str | None = Field(
        default=None,
        description="Exact conclusion or assumption attacked by this argument.",
    )
    status: ArgumentStatus | None = Field(
        default=None, description="Dialectical status of the argument."
    )
    closed_by_budget: bool | None = Field(
        default=None,
        description=(
            "main argument の status が確定した理由が、真の手詰まり（相手が本当に "
            "反論/防御を尽くした）ではなく、探索予算（max_counter_attempts / "
            "max_tree_depth / max_dialogue_turns）の枯渇による "
            "打ち切りだったかどうか。status が None の場合は無意味（None のまま）。"
        ),
    )
    round: int = Field(
        default=1, description="Debate round in which this argument was produced."
    )

    @classmethod
    def from_generated_body(
        cls,
        body: Any,
        *,
        type: ArgumentType,
        agent: AgentName,
        attack: AttackType | None = None,
        target_id: str | None = None,
        target_field: Literal["Conc", "Ass"] | None = None,
        target_statement: str | None = None,
    ) -> Self:
        """LLM 生成の ArgumentBody から Conc/Ass を導出して ArgumentRecord を作る."""
        argument = body.model_dump(exclude_none=True)
        rules = argument.get("rules", [])
        argument["Conc"] = [
            rule["consequent"].strip()
            for rule in rules
            if isinstance(rule, dict)
            and isinstance(rule.get("consequent"), str)
            and rule["consequent"].strip()
        ]
        argument["Ass"] = [
            assumption.strip()
            for rule in rules
            if isinstance(rule, dict) and isinstance(rule.get("antecedent"), dict)
            for assumption in rule["antecedent"].get("weak_negation", [])
            if isinstance(assumption, str) and assumption.strip()
        ]
        return cls(
            type=type,
            argument=json.dumps({"Argument": argument}, ensure_ascii=False, indent=2),
            agent=agent,
            attack=attack,
            target_id=target_id,
            target_field=target_field,
            target_statement=target_statement,
        )

    @property
    def payload(self) -> dict[str, Any]:
        """格納された argument 文字列をパースした JSON dict 全体を返す."""
        return parse_serialized_payload(self.argument)

    @property
    def body(self) -> dict[str, Any]:
        """ペイロード内の Argument 本体 dict を返す."""
        body = self.payload.get("Argument", {})
        return body if isinstance(body, dict) else {}

    @property
    def conclusions(self) -> list[str]:
        """この主張の結論（Conc）リストを返す."""
        return _text_items(self.body.get("Conc"))

    @property
    def assumptions(self) -> list[str]:
        """この主張の仮定（Ass）リストを返す（無ければ rules から導出）."""
        items = _text_items(self.body.get("Ass"))
        if items:
            return items
        rules = self.body.get("rules", [])
        if not isinstance(rules, list):
            return []
        assumptions: list[str] = []
        for rule in rules:
            if isinstance(rule, dict) and isinstance(rule.get("antecedent"), dict):
                assumptions.extend(_text_items(rule["antecedent"].get("weak_negation")))
        return assumptions

    def message_content(self) -> str:
        """履歴メッセージの content（JSON 文字列）を組む.

        round / phase(type) / agent と、攻撃 turn の attack 情報・後追い記録された status を
        畳み込み、本体は Argument ペイロードとして入れる。これで content だけで
        「どのラウンドのどのフェーズの誰の発言で、どこをどう攻撃し、結果どうなったか」が辿れる。
        """
        data: dict[str, Any] = {
            "id": self.id,
            "round": self.round,
            "phase": self.type,
            "agent": self.agent,
        }
        if self.status is not None:
            data["status"] = self.status
        if self.type in {"defeat", "counter"}:
            data["attack"] = self.attack
            data["target_id"] = self.target_id
            data["target_statement"] = self.target_statement
        body = self.body
        # no_schema: argument は構造化 Argument を持たないため、自由記述の本文をそのまま渡す。
        data["Argument"] = body if body else self.argument
        return json.dumps(data, ensure_ascii=False)

    def to_dialogue_dict(self) -> dict[str, Any]:
        """対話ログ出力用に全フィールドを dict 化する."""
        return {
            "id": self.id,
            "round": self.round,
            "type": self.type,
            "argument": self.argument,
            "support": self.support,
            "agent": self.agent,
            "proponent": self.proponent,
            "target_id": self.target_id,
            "attack": self.attack,
            "target_field": self.target_field,
            "target_statement": self.target_statement,
            "status": self.status,
            "closed_by_budget": self.closed_by_budget,
        }


class DialogueNode(BaseModel):
    """dialogue tree (Prakken & Sartor, Definition 4.5/4.6) の1フレーム.

    「P が argument_id を防御している」という文脈を表す。O がこの argument への
    新しい攻撃を出せなくなる（won_by_p）か、途中の攻撃を P が最後まで振り切れない
    （lost_by_p）まで、この1フレーム内で `opponent_move`/`proponent_move` を
    繰り返す。P が攻撃を strictly defeat すると、その反論を argument_id とする
    子フレームを push して探索を1段深くする（再帰）。
    """

    id: str = Field(default_factory=lambda: f"node-{uuid4().hex[:10]}")
    parent_id: str | None = Field(
        default=None, description="この frame を生んだ親 frame の id。根は None。"
    )
    argument_id: str = Field(description="この frame で P が防御している ArgumentRecord.id")
    depth: int = Field(default=0, description="根を 0 とする深さ。")

    # 現在このフレームで O が攻撃中の相手（B）。attack_attempts 回まで別候補に差し替え可。
    current_attacker_id: str | None = Field(default=None)
    attack_attempts: int = Field(
        default=0, description="このフレームで O が試した攻撃 (B) の本数。"
    )
    # current_attacker_id に対して P が試した反論 (C) の本数。B が変わるたびリセット。
    counter_attempts: int = Field(default=0)

    outcome: Literal["open", "won_by_p", "lost_by_p", "undetermined"] = Field(
        default="open"
    )
    # True: 予算切れ（max_counter_attempts/max_tree_depth）による確定。
    # False: 相手が本当に手を出せなくなった/出せた、という理論的な確定。
    closed_by_budget: bool = Field(default=False)


class DefeatRelation(BaseModel):
    """攻撃者と対象の間で検証された defeat 関係の記録."""

    attacker_id: str = Field(description="Id of the attacking argument.")
    target_id: str = Field(description="Id of the attacked argument.")
    attack: AttackType = Field(description="rebut or undercut.")
    target_field: Literal["Conc", "Ass"] | None = Field(
        default=None,
        description="Field in the target argument on which this attack was validated.",
    )
    target_statement: str | None = Field(
        default=None,
        description="Exact target statement on which this attack was validated.",
    )
    valid: bool = Field(
        description="Whether the attack satisfies the defeat condition."
    )
    reason: str | None = Field(
        default=None, description="Short explanation of the validation result."
    )
