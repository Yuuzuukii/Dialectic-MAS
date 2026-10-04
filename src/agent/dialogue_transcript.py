"""議論の発話を、手法に依らない同じ見た目の記録（transcript）に整形する.

最終回答の統合（two_path_finalization）に渡す入力を、schema / no_schema / free_debate で
揃えるためのもの。差が出るのは議論の中身だけにして、手法に固有の情報（攻撃の種類
rebut/undercut、攻撃対象の文、決着状態 justified/overruled/defensible、発話 id、統合ルール）は
入れない。入れるのは次の2つだけ。

- 番号と話者:   ``[Turn 3] AG2``
- 応答先:       ``(new argument)`` または ``(responding to [Turn 2])``

schema の構造化された論証（rules / Conc / Ass）は文章に直し、自由文の手法と同じ見た目にする。
"""

from __future__ import annotations

import json
from typing import Any

TRANSCRIPT_DESCRIPTION = (
    "The record below shows AG1 and AG2 arguing in turn, each from its own stance. "
    "Turns are numbered in order. Each turn is marked either as a new argument or as a response "
    "to an earlier turn."
)


def _strip_period(text: str) -> str:
    stripped = text.strip()
    return stripped[:-1] if stripped.endswith(".") else stripped


def _lowercase_first(text: str) -> str:
    """"So" の後に続く節として埋め込むため先頭を小文字にする（"I" や頭字語はそのまま）."""
    if not text:
        return text
    first_word = text.split(" ", 1)[0].rstrip(".,;:")
    if first_word == "I" or (len(first_word) > 1 and first_word.isupper()):
        return text
    return text[0].lower() + text[1:]


def _strip_leading_connective(text: str) -> str:
    """文頭の Therefore, / Thus, / Hence, を除く（描画側で接続語を付けるため二重化を防ぐ）."""
    stripped = text.strip()
    lowered = stripped.lower()
    for connective in ("therefore,", "therefore ", "thus,", "thus ", "hence,", "hence "):
        if lowered.startswith(connective):
            return stripped[len(connective) :].strip()
    return stripped


def _schema_body(argument: Any) -> dict[str, Any] | None:
    """Return the schema Argument (a dict holding ``rules``), or None when there is none."""
    if isinstance(argument, str):
        try:
            argument = json.loads(argument)
        except json.JSONDecodeError:
            return None
    if not isinstance(argument, dict):
        return None
    body = argument.get("Argument", argument)
    if isinstance(body, dict) and isinstance(body.get("rules"), list):
        return body
    return None


def _schema_text(body: dict[str, Any]) -> str:
    """Render ``rules`` as premise-to-conclusion reasoning steps, without naming any attack type."""
    rules = [rule for rule in body.get("rules", []) if isinstance(rule, dict)]

    def _norm(text: Any) -> str:
        return _strip_period(str(text)).strip().lower()

    # 連鎖では、非末尾の結論が次の rule の前提に再出現する。そのまま描画すると同じ文が
    # 二重に出るので、結論と一致する前提は「つなぎ」とみなして省く。
    consequent_norms = {_norm(rule["consequent"]) for rule in rules if rule.get("consequent")}
    parts: list[str] = []
    assumptions: list[str] = []
    for index, rule in enumerate(rules):
        antecedent = rule.get("antecedent") or {}
        strongs = [
            _strip_leading_connective(_strip_period(premise))
            for premise in antecedent.get("strong") or []
            if premise and premise.strip() and _norm(premise) not in consequent_norms
        ]
        assumptions += [
            _strip_period(item) for item in antecedent.get("weak_negation") or [] if item and item.strip()
        ]
        consequent = _strip_leading_connective(_strip_period(str(rule.get("consequent", ""))))
        grounds = ". ".join(strongs)
        is_last = index == len(rules) - 1
        connector = "Therefore," if is_last else "So"
        connected = consequent if is_last else _lowercase_first(consequent)
        if grounds and connected:
            parts.append(f"{grounds}. {connector} {connected}.")
        elif connected:
            parts.append(f"{connector} {connected}.")
        elif grounds:
            parts.append(f"{grounds}.")
    if assumptions:
        parts.append(f"(This relies on the assumption that {'; '.join(assumptions)}.)")
    return " ".join(parts) if parts else "(no argument)"


def render_argument_text(argument: Any) -> str:
    """発話の本文を、手法に依らない文章にする（schema は rules を文章へ、自由文はそのまま）."""
    body = _schema_body(argument)
    if body is not None:
        return _schema_text(body)
    if isinstance(argument, str) and argument.strip():
        return argument.strip()
    if argument:
        return json.dumps(argument, ensure_ascii=False)
    return "(no argument)"


def _turn_label(number: int, turn: dict[str, Any], id_to_number: dict[str, int]) -> str:
    """番号・話者・応答先のラベル行を作る.

    - schema / no_schema: 主張（type == "main"）は新しい論点。反論・再反論は target_id の発話への応答。
    - free_debate（type を持たない）: 最初の発話は新しい論点、以降は直前の発話への応答。
    """
    agent = turn.get("agent", "?")
    turn_type = turn.get("type")
    if turn_type == "main":
        return f"[Turn {number}] {agent} (new argument)"
    if turn_type is not None:
        target_id = turn.get("target_id")
        if isinstance(target_id, str) and target_id in id_to_number:
            return f"[Turn {number}] {agent} (responding to [Turn {id_to_number[target_id]}])"
        return f"[Turn {number}] {agent} (responding to an earlier turn)"
    if number == 1:
        return f"[Turn {number}] {agent} (new argument)"
    return f"[Turn {number}] {agent} (responding to [Turn {number - 1}])"


def format_transcript(dialogue_history: list[dict[str, Any]]) -> str:
    """議論の全発話を、番号・話者・応答先つきの 1 本のテキストにする."""
    id_to_number = {
        turn["id"]: number
        for number, turn in enumerate(dialogue_history, start=1)
        if isinstance(turn.get("id"), str)
    }
    blocks = [
        f"{_turn_label(number, turn, id_to_number)}\n{render_argument_text(turn.get('argument'))}"
        for number, turn in enumerate(dialogue_history, start=1)
    ]
    return "\n\n".join(blocks)
