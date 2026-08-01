"""LLM の構造化出力（with_structured_output）に使う Pydantic スキーマ定義."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .types import AttackType


# LLM出力：主張（主張可能 + 理由 + Argumentのメイン出力）
class MainArgumentAvailabilityOutput(BaseModel):
    """主張生成の可否と、可能な場合のメイン Argument 出力."""

    can_generate: Literal["YES", "NO"] = Field(
        description=(
            "determining whether you can make an argument regarding the given issue."
        )
    )
    reason: str = Field(description="Brief reason for the availability decision.")
    Argument: ArgumentBody | None = Field(
        default=None,
        description="Required only when can_generate is YES.",
    )


# LLM出力：反論（反論可能 + 攻撃側Argument + 攻撃宣言）
class DefeatingArgumentOutput(BaseModel):
    """反論の可否と、攻撃側 Argument・攻撃宣言（Attack）出力."""

    can_defeat: Literal["YES", "NO"] = Field(
        description="YES only if a valid rebut or undercut is available."
    )
    Argument: ArgumentBody | None = Field(
        default=None, description="Defeating argument body, omitted when NO."
    )
    Attack: AttackMetadata | None = Field(
        default=None,
        description="Attack made by this argument against a specified item in the target argument, omitted when NO.",
    )
    has_new_point: bool = Field(
        default=True,
        description=(
            "True if this attack introduces a genuinely new angle or reasoning not already "
            "tried in an earlier attack against this same target in this thread. False if "
            "this attack is substantially the same claim or reasoning as an earlier attempt, "
            "just reworded."
        ),
    )


# LLM出力：defeat判定（rebutに対するundercut）（undercut可否 + Argumentのメイン出力）
class UndercutOutput(BaseModel):
    """undercut（仮定の無効化）の可否と Argument 出力."""

    can_undercut: Literal["YES", "NO"] = Field(
        description="YES only if a target Ass can be invalidated."
    )
    Argument: ArgumentBody | None = Field(
        default=None, description="Undercutting argument body, omitted when NO."
    )


# LLM出力：B（自分の攻撃）がC（相手の新しいカウンター）にも及ぶかの自己判定
class AttackExtendsOutput(BaseModel):
    """自分の攻撃の対象（statement）が、相手の新しい論証にも依然として存在するかの判定.

    自分の攻撃が依然としてそれを否定しているかどうかの YES/NO 判定.
    """

    attack_extends: Literal["YES", "NO"] = Field(
        description=(
            "YES only if the new counterargument still relies on or still asserts the exact "
            "statement your attack negated. NO if the new counterargument abandoned or "
            "replaced that statement, so your attack no longer applies to it."
        )
    )


# LLM出力：統合（汎化+統合を1ステップで行い、統合済みルールのみを返す）
class IntegrationOutput(BaseModel):
    """統合出力（汎化基準を統合した単一ルール）."""

    Argument: IntegrationBody = Field(description="Integration result.")


# =======================================no_schema 条件用（Argument が自由記述）


# LLM出力：主張（no_schema）。can_generate/reason は構造化のまま、Argument は自由記述。
class MainArgumentAvailabilityOutputFree(BaseModel):
    """主張生成の可否と、可能な場合のメイン Argument（自由記述）."""

    can_generate: Literal["YES", "NO"] = Field(
        description=(
            "determining whether you can make an argument regarding the given issue."
        )
    )
    reason: str = Field(description="Brief reason for the availability decision.")
    Argument: str | None = Field(
        default=None,
        description="Free natural-language argument. Required only when can_generate is YES.",
    )


# LLM出力：反論（no_schema）。can_defeat/Attack は構造化のまま、Argument は自由記述。
class DefeatingArgumentOutputFree(BaseModel):
    """反論の可否と、攻撃側 Argument（自由記述）・攻撃宣言（Attack）出力."""

    can_defeat: Literal["YES", "NO"] = Field(
        description="YES only if a valid rebut or undercut is available."
    )
    Argument: str | None = Field(
        default=None, description="Free natural-language defeating argument, omitted when NO."
    )
    Attack: AttackMetadata | None = Field(
        default=None,
        description="Attack made by this argument against a specified part of the target argument, omitted when NO.",
    )
    has_new_point: bool = Field(
        default=True,
        description=(
            "True if this attack introduces a genuinely new angle or reasoning not already "
            "tried in an earlier attack against this same target in this thread. False if "
            "this attack is substantially the same claim or reasoning as an earlier attempt, "
            "just reworded."
        ),
    )


# LLM出力：undercut（no_schema）。can_undercut は構造化のまま、Argument は自由記述。
class UndercutOutputFree(BaseModel):
    """undercut（仮定の無効化）の可否と Argument（自由記述）出力."""

    can_undercut: Literal["YES", "NO"] = Field(
        description="YES only if a target assumption can be invalidated."
    )
    Argument: str | None = Field(
        default=None, description="Free natural-language undercutting argument, omitted when NO."
    )


# LLM出力：統合（no_schema）。汎化+統合を1ステップで行い、統合ルールを自由記述の文として返す。
class IntegrationBodyFree(BaseModel):
    """統合結果（no_schema; 自由記述の単一ルール）."""

    rule: str = Field(
        description=(
            "A single integrated decision rule, expressed in natural language, generalized from "
            "both sides' warrants and preserving each side's condition-to-conclusion mapping, "
            "applicable to future arguments. Use OR only for conditions supporting the same "
            "outcome. When opposing conditions may coexist, compare them symmetrically rather "
            "than giving either side an automatic veto."
        )
    )


class IntegrationOutputFree(BaseModel):
    """統合出力（no_schema）."""

    Argument: IntegrationBodyFree = Field(description="Integration result.")


# =======================================ヘルパ


# Argumentのメイン出力
class ArgumentBody(BaseModel):
    """連鎖規則の列からなる Argument 本体."""

    rules: list[Rule] = Field(
        default_factory=list,
        description=(
            "Finite sequence of rule instances forming an argument; "
            "the final rule is the warrant of the argument."
        ),
    )


# 先行詞 + 帰結
class Rule(BaseModel):
    """先行詞（antecedent）と帰結（consequent）からなる 1 規則."""

    antecedent: Antecedent = Field(
        description="A conjunction used to lead to a conclusion"
    )
    consequent: str = Field(
        description="A conclusion logically derived from conjunction"
    )


# 先行詞
class Antecedent(BaseModel):
    """規則の先行詞（strong 条件と weak_negation 仮定の連言）."""

    strong: list[str] = Field(
        default_factory=list,
        description="Established assumptions necessary to lead to a conclusion",
    )
    weak_negation: list[str] = Field(
        default_factory=list,
        description="Assumptions necessary to lead to a conclusion",
    )


# 攻撃側が提示する攻撃関係
class AttackMetadata(BaseModel):
    """攻撃側が宣言する攻撃方法（rebut/undercut）と対象参照."""

    method: AttackType = Field(
        description=(
            "Attack method used by this argument: "
            "'rebut' when a conclusion of this argument explicitly negates "
            "a conclusion in the target argument; "
            "'undercut' when a conclusion of this argument explicitly negates "
            "an assumption in the target argument."
        )
    )
    target: TargetReference = Field(
        description="Conclusion or assumption in the target argument attacked by this argument."
    )


# 攻撃側が指定する攻撃対象
class TargetReference(BaseModel):
    """攻撃対象（対象 Argument 内の Conc または Ass の具体文）の参照."""

    field: Literal["Conc", "Ass"] = Field(
        description="Field attacked in the target argument: 'Conc' for a rebut; 'Ass' for an undercut."
    )
    statement: str = Field(
        description="Exact conclusion or assumption in the target argument attacked by this argument."
    )


# 統合出力の要素（汎化+統合を1ステップで行い、統合済みルールのみを保持する）
class IntegrationBody(BaseModel):
    """統合結果（両サイドの warrant を汎化した上でまとめた単一の再利用可能ルール）."""

    consequent: str = Field(
        description=(
            "The shared higher-order decision principle or explicit outcome mapping "
            "that preserves the conclusions supported by both sides' warrants."
        )
    )
    rule: str = Field(
        description=(
            "A single reusable decision rule, generalized from both sides' warrants, "
            "preserving each side's condition-to-conclusion mapping. Use OR only for "
            "alternative conditions that support the same outcome; when conditions support "
            "different outcomes, explicitly map each condition to its corresponding outcome. "
            "When opposing conditions may coexist, compare them using the same evidential "
            "threshold and do not give either side an automatic veto. Do not invent a "
            "precautionary default, burden shift, or tie-breaker absent from the warrants."
        )
    )
