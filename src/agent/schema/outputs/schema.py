from __future__ import annotations

from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

AgentName = Literal["AG1", "AG2"]
DebateStage = Literal["ag1_main_thread", "ag2_main_thread"]
ArgumentType = Literal["main", "defeat", "counter"]
AttackType = Literal["rebut", "undercut"]
ArgumentStatus = Literal["justified", "overruled", "defensible", "undetermined"]


class ArgumentRecord(BaseModel):
    id: str = Field(default_factory=lambda: f"arg-{uuid4().hex[:10]}", description="Internal argument id.")
    type: ArgumentType = Field(description="main for an initial claim, defeat for an opponent attack, counter for a defense.")
    argument: str = Field(description="Serialized argument payload.")
    support: list[str] = Field(default_factory=list, description="Optional supporting facts or references.")
    agent: AgentName = Field(description="Agent that produced this argument.")
    target_id: str | None = Field(default=None, description="Argument id targeted by this defeating argument.")
    attack: AttackType | None = Field(default=None, description="Attack type: rebut or undercut.")
    status: ArgumentStatus | None = Field(default=None, description="Dialectical status of the argument.")

    def to_dialogue_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "argument": self.argument,
            "support": self.support,
            "agent": self.agent,
            "target_id": self.target_id,
            "attack": self.attack,
            "status": self.status,
        }


class DefeatRelation(BaseModel):
    attacker_id: str = Field(description="Id of the attacking argument.")
    target_id: str = Field(description="Id of the attacked argument.")
    attack: AttackType = Field(description="rebut or undercut.")
    valid: bool = Field(description="Whether the attack satisfies the defeat condition.")
    reason: str | None = Field(default=None, description="Short explanation of the validation result.")


class Antecedent(BaseModel):
    strong: list[str] = Field(
        default_factory=list,
        description="Strict premises used to derive the rule consequent.",
    )
    weak_negation: list[str] = Field(
        default_factory=list,
        description="Assumptions of absence of evidence; these form Ass and can be undercut.",
    )


class Rule(BaseModel):
    id: str = Field(description="Rule identifier, such as r1, r2.")
    antecedent: Antecedent = Field(description="Premises of the inference rule.")
    consequent: str = Field(description="Conclusion derived by this rule; collected in Conc.")


class TargetReference(BaseModel):
    argument_id: str = Field(default="", description="Id of the target argument.")
    field: Literal["Conc", "Ass"] = Field(
        default="Conc",
        description="Conc for rebut targets; Ass for undercut targets.",
    )
    statement: str = Field(description="Exact target Conc or Ass statement being attacked.")


class ArgumentBody(BaseModel):
    rules: list[Rule] = Field(
        default_factory=list,
        description="Ordered inference rules that derive the argument conclusions.",
    )
    Conc: list[str] = Field(
        default_factory=list,
        description="Conclusions of the argument, normally the consequents of its rules.",
    )
    Ass: list[str] = Field(
        default_factory=list,
        description="Weak-negation assumptions used by the argument; undercut attacks target these.",
    )


class AttackMetadata(BaseModel):
    attack: AttackType = Field(
        description=(
            "rebut if this argument directly contradicts target Conc; "
            "undercut if it directly invalidates target Ass."
        )
    )
    target: TargetReference = Field(description="The attacked Conc or Ass item.")


class MainArgumentOutput(BaseModel):
    can_generate: Literal["YES", "NO"] = Field(description="YES only if a valid main argument can be constructed.")
    Argument: ArgumentBody | None = Field(default=None, description="Main argument supporting the agent's stance.")


class DefeatingArgumentOutput(BaseModel):
    can_defeat: Literal["YES", "NO"] = Field(description="YES only if a valid rebut or undercut is available.")
    Argument: ArgumentBody | None = Field(default=None, description="Defeating argument body, omitted when NO.")
    Attack: AttackMetadata | None = Field(default=None, description="Attack metadata, omitted when NO.")


class UndercutOutput(BaseModel):
    can_undercut: Literal["YES", "NO"] = Field(description="YES only if a target Ass can be invalidated.")
    Argument: ArgumentBody | None = Field(default=None, description="Undercutting argument body, omitted when NO.")
    Attack: AttackMetadata | None = Field(default=None, description="Undercut metadata, omitted when NO.")


class GeneralizedCriterion(BaseModel):
    id: str = Field(description="Criterion identifier, such as g1.")
    strong: list[str] = Field(default_factory=list, description="Generalized conditions derived from warrants.")
    consequent: str = Field(description="Generalized conclusion derived from the conditions.")


class GeneralizationBody(BaseModel):
    criteria: list[GeneralizedCriterion] = Field(
        default_factory=list,
        description="Reusable criteria extracted from conflicting warrants.",
    )


class GeneralizationArgument(BaseModel):
    Generalization: GeneralizationBody = Field(description="Generalized criteria for later integration.")


class GeneralizationOutput(BaseModel):
    Argument: GeneralizationArgument = Field(description="Generalization result.")


class IntegrationBody(BaseModel):
    strong: list[str] = Field(default_factory=list, description="Integrated generalized conditions.")
    consequent: str = Field(description="Integrated generalized conclusion.")
    rule: str = Field(description="Reusable rule added to integrated_rules for the next dialogue round.")


class IntegrationArgument(BaseModel):
    Integration: IntegrationBody = Field(description="Integrated rule synthesized from generalized criteria.")


class IntegrationOutput(BaseModel):
    Argument: IntegrationArgument = Field(description="Integration result.")
