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
    Argument: ArgumentDraft | None = Field(
        default=None,
        description="Required only when can_generate is YES.",
    )


# LLM出力：反撃を作る前の、自分の過去の発言との比較（非反復の自己点検）
class NoveltyCheck(BaseModel):
    """反撃（counter）が、自分の過去の発言と同じ理由の繰り返しでないかの自己点検.

    Prakken & Sartor の非反復（Def 4.5 条件2）は、P が同じ内容の手を、2度指せないという
    規則で、有限性を保証する。判定は、P 自身が行う。指示文だけで「確認せよ」と言っても、
    確認の結果が出力に残らないので、点検を出力の欄にして、先に（結論の前に）埋めさせる。
    """

    closest_earlier_id: str | None = Field(
        default=None,
        description=(
            "The id of your own earlier argument in this debate (your main argument or an "
            "earlier counterargument) that your planned counterargument is closest to. Null "
            "only if there is none."
        ),
    )
    adds_new_reason: Literal["YES", "NO"] = Field(
        description=(
            "YES only if your planned counterargument rests on a different ground (one of the "
            "distinct reasons your stance gives for your position, or a genuinely different "
            "consideration) than the grounds your earlier arguments used. NO if it only "
            "elaborates a ground you already used: a further example, mechanism or detail, a "
            "restatement, or the same ground aimed at a different part of the attack."
        )
    )
    new_reason: str = Field(
        default="",
        description=(
            "Name the new ground in one sentence, and which ground of your stance it is. Empty "
            "when adds_new_reason is NO."
        ),
    )


# LLM出力：反論（反論可能 + 攻撃側Argument + 攻撃宣言）
class DefeatingArgumentOutput(BaseModel):
    """反論の可否と、攻撃側 Argument・攻撃宣言（Attack）出力."""

    Novelty: NoveltyCheck | None = Field(
        default=None,
        description=(
            "Counterarguments only: fill this in BEFORE deciding can_defeat. Compare your planned "
            "counterargument with your own earlier arguments. Omit for attacks."
        ),
    )
    can_defeat: Literal["YES", "NO"] = Field(
        description="YES only if a valid rebut or undercut is available."
    )
    reason: str = Field(
        default="",
        description="Brief reason for the decision: why NO (what blocks you), or what the argument rests on if YES.",
    )
    Argument: ArgumentDraft | None = Field(
        default=None, description="Defeating argument body, omitted when NO."
    )
    Attack: AttackMetadata | None = Field(
        default=None,
        description="Attack made by this argument against a specified item in the target argument, omitted when NO.",
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

    Novelty: NoveltyCheck | None = Field(
        default=None,
        description=(
            "Fill this in BEFORE deciding can_defeat. Compare your planned argument with your own "
            "earlier arguments in this debate."
        ),
    )
    can_defeat: Literal["YES", "NO"] = Field(
        description="YES only if a valid rebut or undercut is available."
    )
    reason: str = Field(
        default="",
        description="Brief reason for the decision: why NO (what blocks you), or what the argument rests on if YES.",
    )
    Argument: str | None = Field(
        default=None, description="Free natural-language defeating argument, omitted when NO."
    )
    Attack: AttackMetadataFree | None = Field(
        default=None,
        description="Attack made by this argument against a specified part of the target argument, omitted when NO.",
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
        description=(
            "Strong premises: the consequents of the earlier rules named in from_rules, "
            "filled in from those rules (never written by the model)."
        ),
    )
    from_rules: list[int] = Field(
        default_factory=list,
        description="1-based numbers of the earlier rules whose consequents are the strong premises.",
    )
    weak_negation: list[str] = Field(
        default_factory=list,
        description=(
            "Exception clauses ('unless X'): defeasible assumptions of the form 'X is not "
            "the case', held only in the absence of evidence to the contrary. An "
            "undercutting attack defeats one of these by proving that X actually holds."
        ),
    )


# LLM が書く形（強い前提は、文ではなく、前の規則の番号で参照する）
class AntecedentDraft(BaseModel):
    """LLM が書く先行詞（強い前提は、前の規則の番号で指す。weak_negation は文で書く）."""

    from_rules: list[int] = Field(
        default_factory=list,
        description=(
            "Strong premises, given as the numbers (1-based) of EARLIER rules in this Argument "
            "whose consequents this rule relies on. The first rule has none (empty list). "
            "Leave empty when the rule states a claim from your stance without a premise."
        ),
    )
    weak_negation: list[str] = Field(
        default_factory=list,
        description=(
            "Exception clauses ('unless X'): defeasible assumptions of the form 'X is not "
            "the case', held only in the absence of evidence to the contrary. An "
            "undercutting attack defeats one of these by proving that X actually holds."
        ),
    )


class RuleDraft(BaseModel):
    """LLM が書く 1 規則（先行詞 + 帰結）."""

    antecedent: AntecedentDraft = Field(
        description="The earlier rules this rule relies on, and its exception clauses."
    )
    consequent: str = Field(description="The claim this rule concludes.")


class ArgumentDraft(BaseModel):
    """LLM が書く Argument（規則の列）。強い前提の文は、コードが、番号から復元する."""

    rules: list[RuleDraft] = Field(
        default_factory=list,
        description=(
            "Finite sequence of rules forming an argument; the final rule is the warrant of "
            "the argument."
        ),
    )


# 攻撃側が提示する攻撃関係
class AttackMetadata(BaseModel):
    """攻撃側が宣言する攻撃方法（rebut/undercut）と、対象の番号."""

    method: AttackType = Field(
        description=(
            "Attack method used by this argument: "
            "'rebut' when a conclusion of this argument contradicts a conclusion of the "
            "target argument; "
            "'undercut' when a conclusion of this argument contradicts an assumption of "
            "the target argument."
        )
    )
    target: TargetReference = Field(
        description="The item of the target argument that this argument attacks, chosen by number."
    )


# 攻撃側が指定する攻撃対象（番号）
class TargetReference(BaseModel):
    """攻撃対象を、対象の論証から見せられた一覧の番号で指す（文を書き写さない）."""

    number: int = Field(
        description=(
            "The number of the attacked item, copied from the list shown in the instruction: "
            "for a rebut, a number in the target's conclusions; for an undercut, a number in "
            "the target's assumptions; when the target is listed as numbered sentences, the "
            "sentence number."
        )
    )


# 攻撃側が指定する攻撃対象（no_schema: 対象の本文から書き写した文）
class TargetQuote(BaseModel):
    """攻撃対象を、対象の論証の本文から書き写した文（またはフレーズ）で指す（no_schema）."""

    statement: str = Field(
        description=(
            "The sentence or phrase of the target argument that this argument attacks, copied "
            "word for word from the target's text (no paraphrase, no ellipsis, no combining "
            "sentences)."
        )
    )


# 攻撃側が提示する攻撃関係（no_schema）
class AttackMetadataFree(BaseModel):
    """攻撃側が宣言する攻撃方法（rebut/undercut）と、対象の本文から書き写した文（no_schema）."""

    method: AttackType = Field(
        description=(
            "Attack method used by this argument: "
            "'rebut' when a claim of this argument directly opposes a claim of the target "
            "argument; "
            "'undercut' when a claim of this argument establishes that a presumption the "
            "target argument relies on by default does not hold."
        )
    )
    target: TargetQuote = Field(
        description="The words of the target argument that this argument attacks, copied from its text."
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
