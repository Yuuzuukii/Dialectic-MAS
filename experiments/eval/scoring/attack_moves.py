"""議論中の各ターンが rebuttal/undercut/concede/new のどれに当たるかを数える.

仮説「schemaはrebuttal/undercutを明示的に行うようになる」を最終回答を介さず直接
検証するための、議論プロセスそのものに対する指標。

- schema / no_schema: dialogue_history の各ターンがすでに
  `attack: "rebut"|"undercut"|None`, `type: "main"|"defeat"|"counter"` という
  構造化フィールドを持っている（引数生成側が argumentation framework として
  ターンを管理しているため）。よってLLMを使わず機械的に集計できる。
- free_debate / mad: ターンは自由記述の自然文で、上記の構造化フィールドを持たない。
  そのため、直前ターンとの関係をLLMに rebut/undercut/concede/new の4値で
  分類させる（1ターンにつき1回のLLM呼び出し）。
"""

from __future__ import annotations

from typing import Any

from .evaluation_coverage import _parse_json_response

MOVE_KEYS = ("rebut", "undercut", "concede", "new")

MOVE_CLASSIFY_INSTRUCTION = """
You are analyzing one turn of a debate.

Opponent's previous turn:
{prev}

This speaker's current turn:
{curr}

Classify how the current turn relates to the opponent's previous turn:
- "rebut": directly denies/attacks the opponent's overall conclusion or claim.
- "undercut": attacks a specific premise, piece of evidence, or reasoning step
  the opponent relied on, without directly denying their overall conclusion.
- "concede": accepts or agrees with part of the opponent's point.
- "new": introduces a new line of argument without directly engaging the
  opponent's previous turn.

Respond ONLY with a JSON object: {{"move": "rebut"|"undercut"|"concede"|"new"}}
""".strip()


def structural_attack_counts(dialogue_history: list[dict[str, Any]]) -> dict[str, Any]:
    """既存の attack/type フィールドから機械的に集計する（schema / no_schema用、LLM不要）."""
    counts = {key: 0 for key in MOVE_KEYS}
    for turn in dialogue_history:
        attack = turn.get("attack")
        if attack == "rebut":
            counts["rebut"] += 1
        elif attack == "undercut":
            counts["undercut"] += 1
        else:
            counts["new"] += 1  # main turn（新規主張）。schema側にconcedeという型は無い。
    counts["total"] = len(dialogue_history)
    return counts


def _turn_text(turn: dict[str, Any]) -> str:
    argument = turn.get("argument")
    return argument.strip() if isinstance(argument, str) and argument.strip() else "(no argument)"


def llm_attack_counts(
    dialogue_history: list[dict[str, Any]], judge_model: Any
) -> dict[str, Any]:
    """free_debate / mad 用: 直前ターンとの関係をLLMで rebut/undercut/concede/new に分類する.

    先頭ターン（応答対象が無い最初の発言）は "new" として数える。
    """
    counts = {key: 0 for key in MOVE_KEYS}
    failures = 0
    for i, turn in enumerate(dialogue_history):
        if i == 0:
            counts["new"] += 1
            continue
        prev_text = _turn_text(dialogue_history[i - 1])
        curr_text = _turn_text(turn)
        prompt = MOVE_CLASSIFY_INSTRUCTION.format(prev=prev_text, curr=curr_text)
        try:
            raw = judge_model.invoke(prompt)
            parsed = _parse_json_response(raw)
            move = parsed.get("move")
            if move not in MOVE_KEYS:
                raise ValueError(f"unexpected move: {move!r}")
            counts[move] += 1
        except Exception as e:  # noqa: BLE001 - 分類失敗は診断出力して継続
            print(f"Attack-move classification failed for turn {i}: {e}")  # noqa: T201
            failures += 1
    counts["total"] = len(dialogue_history)
    counts["failures"] = failures
    return counts


def evaluate_attack_moves(log: dict[str, Any], judge_model: Any) -> dict[str, Any]:
    """1件のログについて、ターン単位の rebut/undercut/concede/new 内訳を返す.

    method が schema/no_schema なら構造フィールドから機械的に（LLM不要）、
    free_debate/mad ならLLM分類で集計する。
    """
    dialogue_history: list[dict[str, Any]] = log.get("dialogue_history") or []
    method = log.get("method") or log.get("mode")

    if not dialogue_history:
        return {key: 0 for key in (*MOVE_KEYS, "total")}

    is_structural = any(turn.get("attack") is not None for turn in dialogue_history) or method in (
        "schema",
        "no_schema",
    )
    if is_structural:
        return structural_attack_counts(dialogue_history)
    return llm_attack_counts(dialogue_history, judge_model)


__all__ = [
    "MOVE_KEYS",
    "MOVE_CLASSIFY_INSTRUCTION",
    "structural_attack_counts",
    "llm_attack_counts",
    "evaluate_attack_moves",
]
