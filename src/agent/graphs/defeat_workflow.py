from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

try:
    from ..schema.outputs.schema import (
        AgentName,
        ArgumentRecord,
        AttackType,
        DefeatRelation,
    )
except ImportError:  # pragma: no cover - supports LangGraph file-path loading.
    from schema.outputs.schema import (
        AgentName,
        ArgumentRecord,
        AttackType,
        DefeatRelation,
    )

BlockerGenerator = Callable[[Any, AgentName, ArgumentRecord], Awaitable[ArgumentRecord | None]]


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


def extract_json_from_argument(argument_text: str | None) -> dict[str, Any]:
    if not argument_text:
        return {}
    try:
        if "```json" in argument_text:
            json_start = argument_text.find("```json") + 7
            json_end = argument_text.find("```", json_start)
            json_str = argument_text[json_start:json_end].strip()
        elif "```" in argument_text:
            json_start = argument_text.find("```") + 3
            json_end = argument_text.find("```", json_start)
            json_str = argument_text[json_start:json_end].strip()
        else:
            json_start = argument_text.find("{")
            json_end = argument_text.rfind("}") + 1
            json_str = argument_text[json_start:json_end].strip()
        return json.loads(json_str)
    except Exception:
        return {}


def argument_payload(record: ArgumentRecord | None) -> dict[str, Any]:
    if record is None:
        return {}
    return extract_json_from_argument(record.argument)


def argument_body(record: ArgumentRecord | None) -> dict[str, Any]:
    data = argument_payload(record)
    body = data.get("Argument", {})
    return body if isinstance(body, dict) else {}


def list_text(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def conc(record: ArgumentRecord | None) -> list[str]:
    return list_text(argument_body(record).get("Conc"))


def ass(record: ArgumentRecord | None) -> list[str]:
    body = argument_body(record)
    items = list_text(body.get("Ass"))
    if items:
        return items
    rules = body.get("rules", [])
    if not isinstance(rules, list):
        return []
    flattened: list[str] = []
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        antecedent = rule.get("antecedent", {})
        if isinstance(antecedent, dict):
            flattened.extend(list_text(antecedent.get("weak_negation")))
    return flattened


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


def rebuts(attacker: ArgumentRecord, target: ArgumentRecord) -> bool:
    return any(directly_contradicts(a, t) for a in conc(attacker) for t in conc(target))


def undercuts(attacker: ArgumentRecord, target: ArgumentRecord) -> bool:
    return bool(conc(attacker)) and bool(ass(target))


def valid_declared_attack(attacker: ArgumentRecord, target: ArgumentRecord) -> bool:
    if attacker.attack == "undercut":
        return undercuts(attacker, target)
    if attacker.attack == "rebut":
        return rebuts(attacker, target)
    return False


def infer_attack(attacker: ArgumentRecord, target: ArgumentRecord) -> AttackType | None:
    if attacker.attack == "undercut" and undercuts(attacker, target):
        return "undercut"
    if attacker.attack == "rebut" and rebuts(attacker, target):
        return "rebut"
    if rebuts(attacker, target):
        return "rebut"
    if undercuts(attacker, target):
        return "undercut"
    return None


def relation(
    attacker: ArgumentRecord,
    target: ArgumentRecord,
    valid: bool,
    reason: str,
    attack: AttackType | None = None,
) -> DefeatRelation:
    return DefeatRelation(
        attacker_id=attacker.id,
        target_id=target.id,
        attack=attack or attacker.attack or "rebut",
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
    attack = infer_attack(attacker, target)
    if attack is None:
        return DefeatSubgraphResult(
            defeats=False,
            attack=None,
            relations=[relation(attacker, target, False, f"{relation_context}: no valid rebut or undercut")],
        )

    if persist_metadata:
        attacker.attack = attack
        attacker.target_id = target.id
    if attack == "undercut":
        return DefeatSubgraphResult(
            defeats=True,
            attack=attack,
            relations=[relation(attacker, target, True, f"{relation_context}: undercut defeats target", attack)],
        )

    if allow_generated_blocker and blocker_generator is not None:
        blocker = await blocker_generator(state, defender, attacker)
        if blocker is not None:
            return DefeatSubgraphResult(
                defeats=False,
                attack=attack,
                blocker=blocker,
                relations=[
                    relation(blocker, attacker, True, f"{relation_context}: rebut blocked by undercut")
                ],
            )

    return DefeatSubgraphResult(
        defeats=True,
        attack=attack,
        relations=[relation(attacker, target, True, f"{relation_context}: rebut not blocked by undercut", attack)],
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
