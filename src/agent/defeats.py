from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

try:
    from .schema.state import ArgumentRecord, DefeatRelation
    from .schema.types import AgentName, AttackType
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
    statement: str | None


def attack_from_metadata(attacker: ArgumentRecord) -> AttackMatch | None:
    """LLM が宣言した攻撃メタデータから AttackMatch を生成する。"""
    if attacker.attack is None:
        return None
    field: TargetField = "Conc" if attacker.attack == "rebut" else "Ass"
    return AttackMatch(attacker.attack, field, attacker.target_statement)


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
    match = attack_from_metadata(attacker)
    if match is None:
        return DefeatSubgraphResult(
            defeats=False,
            attack=None,
            relations=[relation(attacker, target, None, False, f"{relation_context}: no attack metadata declared by LLM")],
        )

    if persist_metadata:
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
                        attack_from_metadata(blocker),
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
