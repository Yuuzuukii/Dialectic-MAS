"""Argumentation Model: 攻撃の成否判定（rebut/undercut）と defeat 関係を計算する."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

from .schema.state import ArgumentRecord, DefeatRelation
from .schema.types import AgentName, AttackType

# 防御側のすでにある論証（own）が、相手の rebut（attack）を undercut しているかの判定。
# undercut しているならその理由を返し、していなければ None（新しい論証は作らない）。
UndercutCheck = Callable[[ArgumentRecord, ArgumentRecord], Awaitable[str | None]]
TargetField = Literal["Conc", "Ass"]


def _log(msg: str) -> None:
    print(msg, flush=True)  # noqa: T201  # 議論進行を端末へ出すための意図的なログ。


@dataclass
class AttackEvaluation:
    """単一方向の攻撃判定結果（成否・攻撃種別・関係・対象側の undercut の理由）."""

    defeats: bool
    attack: AttackType | None
    relations: list[DefeatRelation]
    # rebut が defeat にならなかった理由が「対象側のすでにある論証が攻撃を undercut している」
    # ことのとき、その理由。それ以外は None。
    target_undercuts: str | None = None


@dataclass(frozen=True)
class AttackMatch:
    """攻撃メタデータから導いた攻撃種別・対象フィールド・対象文の組."""

    method: AttackType
    field: TargetField
    statement: str | None


def _normalize(text: str) -> str:
    return text.strip().rstrip(".").strip().lower()


def attack_from_metadata(attacker: ArgumentRecord) -> AttackMatch | None:
    """LLM が宣言した攻撃メタデータから AttackMatch を生成する."""
    if attacker.attack is None:
        return None
    field: TargetField = "Conc" if attacker.attack == "rebut" else "Ass"
    return AttackMatch(attacker.attack, field, attacker.target_statement)


def target_statement_exists(match: AttackMatch, target: ArgumentRecord) -> bool:
    """LLM が宣言した target_statement が、対象の実際の Conc/Ass に存在するか検証する.

    Definition 2.8 の attack は論証の実際の内容から客観的に決まる関係であり、
    攻撃側が自己申告する target_statement をそのまま信用してよい理由にはならない。
    no_schema（target.body が空）では Conc/Ass が構造化されていないため検証できず、
    常に True とする。
    """
    if not target.body:
        return True
    candidates = target.conclusions if match.field == "Conc" else target.assumptions
    if match.statement is None:
        return False
    wanted = _normalize(match.statement)
    return any(_normalize(c) == wanted for c in candidates)


def relation(
    attacker: ArgumentRecord,
    target: ArgumentRecord,
    match: AttackMatch | None,
    valid: bool,
    reason: str,
) -> DefeatRelation:
    """攻撃者・対象・判定結果から DefeatRelation レコードを組み立てる."""
    return DefeatRelation(
        attacker_id=attacker.id,
        target_id=target.id,
        attack=match.method if match else attacker.attack or "rebut",
        target_field=match.field if match else attacker.target_field,
        target_statement=match.statement if match else attacker.target_statement,
        valid=valid,
        reason=reason,
    )


async def evaluate_attack(
    state: Any,
    attacker: ArgumentRecord,
    target: ArgumentRecord,
    defender: AgentName,
    *,
    relation_context: str,
    undercut_check: UndercutCheck | None = None,
    persist_metadata: bool = True,
) -> AttackEvaluation:
    """攻撃者が対象を破れるか判定する。rebut は、対象側のすでにある論証が攻撃を undercut していなければ defeat."""
    _log(f"[argumentation_model] {relation_context}")
    match = attack_from_metadata(attacker)
    if match is None:
        _log("  → no attack metadata: not defeated")
        return AttackEvaluation(
            defeats=False,
            attack=None,
            relations=[
                relation(
                    attacker,
                    target,
                    None,
                    False,
                    f"{relation_context}: no attack metadata declared by LLM",
                )
            ],
        )

    _log(f'  attack: {match.method} on {match.field} — "{match.statement}"')

    if not target_statement_exists(match, target):
        _log("  → declared target_statement not found in target's Conc/Ass: not defeated")
        return AttackEvaluation(
            defeats=False,
            attack=match.method,
            relations=[
                relation(
                    attacker,
                    target,
                    match,
                    False,
                    f"{relation_context}: declared target_statement not present in target",
                )
            ],
        )

    if persist_metadata:
        attacker.target_id = target.id
        attacker.target_field = match.field
        attacker.target_statement = match.statement

    if match.method == "undercut":
        _log("  → undercut: defeated")
        return AttackEvaluation(
            defeats=True,
            attack=match.method,
            relations=[
                relation(
                    attacker,
                    target,
                    match,
                    True,
                    f"{relation_context}: undercut defeats target",
                )
            ],
        )

    if undercut_check is not None:
        _log(f"  rebut detected — checking whether {target.id} already undercuts {attacker.id}")
        reason = await undercut_check(target, attacker)
        if reason is not None:
            _log("  → target already undercuts the rebut: not defeated")
            return AttackEvaluation(
                defeats=False,
                attack=match.method,
                target_undercuts=reason,
                relations=[
                    relation(
                        target,
                        attacker,
                        AttackMatch("undercut", "Ass", None),
                        True,
                        f"{relation_context}: rebut not defeating, the target undercuts it — {reason}",
                    )
                ],
            )
        _log("  → target does not undercut the rebut: rebut succeeds, defeated")

    return AttackEvaluation(
        defeats=True,
        attack=match.method,
        relations=[
            relation(
                attacker,
                target,
                match,
                True,
                f"{relation_context}: rebut not undercut by the target",
            )
        ],
    )
