from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .types import AttackType


# LLM出力：主張（主張可能 + 理由 + Argumentのメイン出力）
class MainArgumentAvailabilityOutput(BaseModel):
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
    can_defeat: Literal["YES", "NO"] = Field(description="YES only if a valid rebut or undercut is available.")
    Argument: ArgumentBody | None = Field(default=None, description="Defeating argument body, omitted when NO.")
    Attack: AttackMetadata | None = Field(
        default=None,
        description="Attack made by this argument against a specified item in the target argument, omitted when NO.",
    )

# LLM出力：defeat判定（rebutに対するundercut）（undercut可否 + Argumentのメイン出力）
class UndercutOutput(BaseModel):
    can_undercut: Literal["YES", "NO"] = Field(description="YES only if a target Ass can be invalidated.")
    Argument: ArgumentBody | None = Field(default=None, description="Undercutting argument body, omitted when NO.")

# LLM出力：汎化
class GeneralizationOutput(BaseModel):
    Argument: list[GeneralizedCriterion] = Field(
        default_factory=list,
        description="Reusable criteria extracted from conflicting warrants.",
    )

# LLM出力：統合
class IntegrationOutput(BaseModel):
    Argument: IntegrationBody = Field(description="Integration result.")

# =======================================ヘルパ

# Argumentのメイン出力
class ArgumentBody(BaseModel):
    rules: list[Rule] = Field(
        default_factory=list,
        description=(
            "Finite sequence of rule instances forming an argument. "
            "Each strong antecedent must be supported by an earlier consequent; "
            "each non-final consequent must support a later rule; "
            "no two rules may have the same consequent; "
            "the final rule is the warrant of the argument."
        ),
    )

# 先行詞 + 帰結
class Rule(BaseModel):
    antecedent: Antecedent = Field(description="A conjunction used to lead to a conclusion")
    consequent: str = Field(description="A conclusion logically derived from conjunction")

# 先行詞
class Antecedent(BaseModel):
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
    field: Literal["Conc", "Ass"] = Field(
        description="Field attacked in the target argument: 'Conc' for a rebut; 'Ass' for an undercut."
    )
    statement: str = Field(
        description="Exact conclusion or assumption in the target argument attacked by this argument."
    )

# 汎化出力の要素
class GeneralizedCriterion(BaseModel):
    strong: list[str] = Field(default_factory=list, description="Generalized conditions derived from warrants.")
    consequent: str = Field(description="Generalized conclusion derived from the conditions.")
    principle: str = Field(description="The underlying value or principle that makes this criterion rationally compelling (e.g. 'portability', 'practical performance').")

# 統合出力の要素
class IntegrationBody(BaseModel):
    consequent: str = Field(description="Integrated generalized conclusion.")
    rule: str = Field(
        description=(
            "A single reusable rule formed by taking every 'strong' condition from all generalized criteria "
            "and combining them with OR as alternative sufficient conditions leading to the consequent. "
        )
    )
