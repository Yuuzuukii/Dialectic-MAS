from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

try:
    from ..schema.state import ArgumentRecord, DefeatRelation
    from ..schema.types import AgentName, AttackType
except ImportError:  # pragma: no cover - supports LangGraph file-path loading.
    from schema.state import ArgumentRecord, DefeatRelation
    from schema.types import AgentName, AttackType

BlockerGenerator = Callable[[Any, AgentName, ArgumentRecord], Awaitable[ArgumentRecord | None]]
TargetField = Literal["Conc", "Ass"]


@dataclass
class DefeatSubgraphResult:
    defeats: bool
    attack: AttackType | None
    relations: list[DefeatRelation]
    blocker: ArgumentRecord | None = None


@dataclass
class StrictDefeatSubgraphResult:
    strictly_defeats: bool
    forward: DefeatSubgraphResult | None
    reverse: DefeatSubgraphResult | None


@dataclass(frozen=True)
class AttackMatch:
    method: AttackType
    field: TargetField
    statement: str


def normalize_statement(item: str) -> str:
    text = item.lower()
    text = text.replace("purchase", "buy").replace("purchasing", "buying")
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return " ".join(text.split())


def recommendation_object(statement: str) -> str | None:
    text = normalize_statement(statement)
    match = re.search(r"\bbuy\s+(.+)$", text)
    if not match:
        return None
    obj = match.group(1)
    obj = re.sub(r"^(a|an|the)\s+", "", obj)
    return obj.strip() or None


def is_negative(statement: str) -> bool:
    text = normalize_statement(statement)
    return any(marker in text for marker in (" should not ", " not buy ", " cannot ", " can not "))


def directly_contradicts(left: str, right: str) -> bool:
    left_norm = normalize_statement(left)
    right_norm = normalize_statement(right)
    left_obj = recommendation_object(left)
    right_obj = recommendation_object(right)
    if left_obj and right_obj:
        return left_obj == right_obj and is_negative(left) != is_negative(right)
    if left_norm == right_norm:
        return False
    return (
        left_norm == f"not {right_norm}"
        or right_norm == f"not {left_norm}"
        or left_norm.replace(" not ", " ") == right_norm
        or right_norm.replace(" not ", " ") == left_norm
    )


def find_attack(attacker: ArgumentRecord, target: ArgumentRecord) -> AttackMatch | None:
    methods: tuple[AttackType, ...] = (attacker.attack,) if attacker.attack else ("rebut", "undercut")
    for method in methods:
        field: TargetField = "Conc" if method == "rebut" else "Ass"
        if attacker.target_field is not None and attacker.target_field != field:
            continue
        statements = target.conclusions if field == "Conc" else target.assumptions
        for statement in statements:
            if attacker.target_statement is not None and statement != attacker.target_statement:
                continue
            if any(directly_contradicts(conclusion, statement) for conclusion in attacker.conclusions):
                return AttackMatch(method, field, statement)
    return None


def relation(
    attacker: ArgumentRecord,
    target: ArgumentRecord,
    match: AttackMatch | None,
    valid: bool,
    reason: str,
) -> DefeatRelation:
    return DefeatRelation(
        attacker_id=attacker.id,
        target_id=target.id,
        attack=match.method if match else attacker.attack or "rebut",
        target_field=match.field if match else attacker.target_field,
        target_statement=match.statement if match else attacker.target_statement,
        valid=valid,
        reason=reason,
    )


async def run_defeat_subgraph(
    state: Any,
    attacker: ArgumentRecord,
    target: ArgumentRecord,
    defender: AgentName,
    *,
    relation_context: str,
    blocker_generator: BlockerGenerator | None = None,
    allow_generated_blocker: bool = True,
    persist_metadata: bool = True,
) -> DefeatSubgraphResult:
    match = find_attack(attacker, target)
    if match is None:
        return DefeatSubgraphResult(
            defeats=False,
            attack=None,
            relations=[relation(attacker, target, None, False, f"{relation_context}: no valid rebut or undercut")],
        )

    if persist_metadata:
        attacker.attack = match.method
        attacker.target_id = target.id
        attacker.target_field = match.field
        attacker.target_statement = match.statement
    if match.method == "undercut":
        return DefeatSubgraphResult(
            defeats=True,
            attack=match.method,
            relations=[relation(attacker, target, match, True, f"{relation_context}: undercut defeats target")],
        )

    if allow_generated_blocker and blocker_generator is not None:
        blocker = await blocker_generator(state, defender, attacker)
        if blocker is not None:
            return DefeatSubgraphResult(
                defeats=False,
                attack=match.method,
                blocker=blocker,
                relations=[
                    relation(
                        blocker,
                        attacker,
                        find_attack(blocker, attacker),
                        True,
                        f"{relation_context}: rebut blocked by undercut",
                    )
                ],
            )

    return DefeatSubgraphResult(
        defeats=True,
        attack=match.method,
        relations=[relation(attacker, target, match, True, f"{relation_context}: rebut not blocked by undercut")],
    )


async def run_strict_defeat_subgraph(
    state: Any,
    x: ArgumentRecord,
    y: ArgumentRecord,
    *,
    forward_defender: AgentName,
    reverse_defender: AgentName,
    blocker_generator: BlockerGenerator | None = None,
    forward_already_true: bool = False,
) -> StrictDefeatSubgraphResult:
    forward = None
    if not forward_already_true:
        forward = await run_defeat_subgraph(
            state,
            x,
            y,
            forward_defender,
            relation_context=f"{x.id} defeats {y.id}",
            blocker_generator=blocker_generator,
            allow_generated_blocker=True,
        )
        if not forward.defeats:
            return StrictDefeatSubgraphResult(False, forward, None)

    reverse = await run_defeat_subgraph(
        state,
        y,
        x,
        reverse_defender,
        relation_context=f"{y.id} defeats {x.id}",
        blocker_generator=blocker_generator,
        allow_generated_blocker=False,
        persist_metadata=False,
    )
    return StrictDefeatSubgraphResult(not reverse.defeats, forward, reverse)
