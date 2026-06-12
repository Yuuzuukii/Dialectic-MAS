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

    id: str = Field(default_factory=lambda: f"arg-{uuid4().hex[:10]}", description="Internal argument id.")
    type: ArgumentType = Field(description="main for an initial claim, defeat for an opponent attack, counter for a defense.")
    argument: str = Field(description="Serialized argument payload.")
    support: list[str] = Field(default_factory=list, description="Optional supporting facts or references.")
    agent: AgentName = Field(description="Agent that produced this argument.")
    target_id: str | None = Field(default=None, description="Argument id targeted by this defeating argument.")
    attack: AttackType | None = Field(default=None, description="Attack type: rebut or undercut.")
    target_field: Literal["Conc", "Ass"] | None = Field(
        default=None,
        description="Field in the targeted argument attacked by this argument.",
    )
    target_statement: str | None = Field(
        default=None,
        description="Exact conclusion or assumption attacked by this argument.",
    )
    status: ArgumentStatus | None = Field(default=None, description="Dialectical status of the argument.")
    round: int = Field(default=1, description="Debate round in which this argument was produced.")

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
        data["Argument"] = self.body
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
            "target_id": self.target_id,
            "attack": self.attack,
            "target_field": self.target_field,
            "target_statement": self.target_statement,
            "status": self.status,
        }


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
    valid: bool = Field(description="Whether the attack satisfies the defeat condition.")
    reason: str | None = Field(default=None, description="Short explanation of the validation result.")
