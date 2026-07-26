"""新ルーブリック（Constructiveness / Constraint Preservation）による LLM 評価.

既存の `evaluation.py` の4軸（Coherence/Originality/Dialecticality/Validity）は、
holistic な 1〜10 スコアのブレが大きく（同一内容の再評価でも標準偏差 0.7〜1.0 程度）、
指導教員から指摘された以下2点を直接測れていなかった:

  1. 非建設的な反論の応酬を抑制できているか        -> Constructiveness
  2. 各論証で提示された制約・要求を保持した統合論証を生成できているか -> Constraint Preservation

この2軸は「与える入力」が異なるため、意図的に**別々のLLM呼び出し**として実装する:

- Constructiveness: 従来通り question / stance / debate_transcript を渡し、
  対話の応酬そのものが建設的かを評価する。
- Constraint Preservation: **debate_transcript は渡さない**。question / stance /
  final_answer のみを渡し、最終回答が両者のスタンスで提示された制約・要求を
  （対話中の経緯とは独立に）保持できているかだけを評価する。

transcript の整形（schema の JSON→自然文変換、攻撃対象の明示、integrated rule の
挿入など）は `evaluation.py` の `build_eval_input` をそのまま再利用し、ここでは
新規に実装しない（二重管理を避けるため）。
"""

from __future__ import annotations

import json
from typing import Any

from src.eval.evaluation import build_eval_input, efficiency_metrics

AXES_V2 = ("constructiveness", "constraint_preservation")


CONSTRUCTIVENESS_INSTRUCTION = """
You are an evaluator LLM. Your task is to rate how CONSTRUCTIVE the exchange of
objections in the following debate transcript is, on a scale from 1 to 10.

Constructiveness means each objection in the transcript avoids non-constructive
exchange and instead advances the debate. Judge each objection (rebut/undercut/counter
turn) against these failure modes:
  - Repeats the objecting side's own prior claim essentially unchanged, without engaging
    the specific point it targets.
  - Is a generic or vague rebuttal that could apply to almost any claim, rather than
    engaging the specific claim or assumption actually made by the target.
  - Ignores or talks past the target's specific point (a non-sequitur relative to what
    was actually said).
  - Restates a point that was already raised and answered earlier in the transcript,
    without adding new reasoning.

A high-constructiveness debate is one where every objection engages a specific point
with new reasoning, so that the exchange visibly narrows or sharpens over time. A
low-constructiveness debate is dominated by circular restatement, generic rebuttals,
or turns that talk past each other.

Scoring rubric:
  9–10: Outstanding – virtually every objection is specific and advances the exchange.
  7–8:  Good – mostly constructive, with minor lapses (one or two generic/repetitive turns).
  5–6:  Adequate – a mix of constructive and non-constructive turns.
  1–4:  Weak – dominated by repetition, generic rebuttals, or turns that talk past each other.

IMPORTANT: Rate strictly. Perfect scores are rare.

Evaluate the following debate:

Question:
{question}

AG1 Stance:
{agent1_stance}

AG2 Stance:
{agent2_stance}

Debate Transcript (chronological, each turn is one agent's argument):
{debate_transcript}

Respond ONLY with a JSON object:
{{
  "constructiveness": <int>,
  "evaluator_model": "<model name>"
}}
""".strip()


CONSTRAINT_PRESERVATION_INSTRUCTION = """
You are an evaluator LLM. Your task is to rate, on a scale from 1 to 10, how well the
final answer below PRESERVES the constraints and requirements presented in each side's
stance.

You are NOT shown the debate transcript. Judge only whether the final answer, read
against the two stances, respects the specific constraints, conditions, and requirements
each side raised — either by explicitly satisfying/addressing them, or by taking a
position that a reasonable reading of both stances would still endorse — rather than
silently dropping one side's requirements in favor of a generic compromise or an
unqualified endorsement of only one side.

Concretely, penalize a final answer that:
  - Ignores a specific, substantive requirement or condition named in one side's stance
    (e.g., a named threshold, exception, or precondition) without acknowledging it.
  - Resolves the disagreement with a generic compromise that doesn't engage with the
    specific substance either side raised (e.g., "there are valid points on both sides"
    without saying what those points imply for the answer).
  - Adopts one side's position wholesale while leaving the other side's stated
    requirements completely unaddressed.

Reward a final answer that:
  - Names the specific constraints/requirements from both stances and shows how the
    answer accounts for them (satisfies, qualifies, or explains why one is overridden).
  - Reaches a position that could not be reached without taking both sides' specific
    requirements into account (rather than a position reachable from the question alone).
  - Reflects the integrated rules below (when provided): these were agreed by BOTH
    sides during the debate, so a strong answer visibly builds on them rather than
    ignoring them or contradicting them.

Scoring rubric:
  9–10: Outstanding – explicitly accounts for the substantive requirements from both stances.
  7–8:  Good – accounts for most requirements, with minor omissions.
  5–6:  Adequate – addresses the general thrust of both sides but drops some specifics.
  1–4:  Weak – ignores substantive requirements from one or both sides, or is a generic
        compromise that doesn't engage with what was specifically demanded.

IMPORTANT: Rate strictly. Perfect scores are rare.

Question:
{question}

AG1 Stance:
{agent1_stance}

AG2 Stance:
{agent2_stance}
{integrated_rules_block}
Final Answer:
{final_answer}

Respond ONLY with a JSON object:
{{
  "constraint_preservation": <int>,
  "evaluator_model": "<model name>"
}}
""".strip()


def _parse_json_response(raw: str, evaluator_model: Any) -> dict[str, Any]:
    """LLM の生テキスト応答から JSON 部分を取り出してパースする（コードフェンス対応）."""
    text = raw.strip()
    if "```json" in text:
        start = text.find("```json") + len("```json")
        text = text[start : text.find("```", start)].strip()
    elif text.startswith("```"):
        text = text[3 : text.rfind("```")].strip()
    else:
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            text = text[start:end]
    result: dict[str, Any] = json.loads(text)
    result["evaluator_model"] = evaluator_model.model
    return result


def evaluate_constructiveness(
    eval_input: dict[str, Any], evaluator_model: Any
) -> dict[str, Any]:
    """debate_transcript を含めて Constructiveness のみを採点する."""
    prompt = CONSTRUCTIVENESS_INSTRUCTION.format(
        question=eval_input["question"],
        agent1_stance=eval_input["agent1_stance"],
        agent2_stance=eval_input["agent2_stance"],
        debate_transcript=eval_input["debate_transcript"],
    )
    try:
        raw = evaluator_model.invoke(prompt)
        return _parse_json_response(raw, evaluator_model)
    except Exception as e:  # noqa: BLE001 - 評価失敗を診断出力して継続する
        print(f"Constructiveness evaluation failed: {e}")  # noqa: T201
        return {
            "constructiveness": None,
            "evaluator_model": getattr(evaluator_model, "model", "unknown"),
        }


def evaluate_constructiveness_debate_only(
    log: dict[str, Any], evaluator_model: Any
) -> dict[str, Any]:
    """ターン単位の議論（main/defeat/counter）だけで Constructiveness を採点する.

    統合ルールの文面を含めない。final_answer はそもそも CONSTRUCTIVENESS_INSTRUCTION
    に渡していないので、これで「議論部分だけ」（統合フェーズの生成物も最終回答も
    含まない）を評価できる。
    """
    eval_input = build_eval_input(log, include_integrated_rules=False)
    return evaluate_constructiveness(eval_input, evaluator_model)


def _integrated_rules_block(eval_input: dict[str, Any]) -> str:
    """統合ルールを constraint_preservation プロンプト用のブロックへ整形する（無ければ空文字）."""
    rules = eval_input.get("integrated_rules") or []
    rules = [str(r).strip() for r in rules if str(r).strip()]
    if not rules:
        return ""
    bullet = "\n".join(f"- {r}" for r in rules)
    return (
        "\nIntegrated rules (agreed by both sides during the debate):\n" + bullet + "\n"
    )


def evaluate_constraint_preservation(
    eval_input: dict[str, Any], evaluator_model: Any
) -> dict[str, Any]:
    """スタンス・最終回答・integrated_rules で Constraint Preservation を採点する（transcript は渡さない）.

    integrated_rules（両者が合意した warrant の蒸留）は schema 系の「両スタンスを
    取り込む」機構そのものだが、従来は final_answer だけを見ており、この機構が
    採点にまったく反映されていなかった。ここで入力に加える。
    """
    prompt = CONSTRAINT_PRESERVATION_INSTRUCTION.format(
        question=eval_input["question"],
        agent1_stance=eval_input["agent1_stance"],
        agent2_stance=eval_input["agent2_stance"],
        integrated_rules_block=_integrated_rules_block(eval_input),
        final_answer=eval_input["final_answer"],
    )
    try:
        raw = evaluator_model.invoke(prompt)
        return _parse_json_response(raw, evaluator_model)
    except Exception as e:  # noqa: BLE001
        print(f"Constraint-preservation evaluation failed: {e}")  # noqa: T201
        return {
            "constraint_preservation": None,
            "evaluator_model": getattr(evaluator_model, "model", "unknown"),
        }


def structural_constructiveness(log: dict[str, Any]) -> dict[str, Any]:
    """dialogue_history の attack メタデータから建設性の決定論的サブ指標を計算する.

    LLM 採点（散文の流暢さに引きずられる）が拾えない「構造的な建設性」を測る。
    schema / no_schema 両方に適用可能（どちらも attack/target_id/target_statement を持つ）。

    - specificity     : 攻撃ターンのうち、実在の先行ターン(target_id)を指し、かつ具体的な
                        対象文(target_statement)を持つ割合。
    - target_diversity: 攻撃ターンのうち、(target_id, target_statement) が過去の攻撃と重複
                        しない割合（同じ点の蒸し返しでない度合い）。
    - structural_constructiveness: 上記2つの平均（0–1）。
    """
    history = log.get("dialogue_history") or []
    ids = {r.get("id") for r in history if isinstance(r, dict) and r.get("id")}
    attacks = [
        r for r in history if isinstance(r, dict) and r.get("attack")
    ]
    n = len(attacks)
    if n == 0:
        return {
            "specificity": None,
            "target_diversity": None,
            "structural_constructiveness": None,
            "n_attacks": 0,
        }
    specific = 0
    novel = 0
    seen: set[tuple[Any, str]] = set()
    for a in attacks:
        target_id = a.get("target_id")
        statement = (a.get("target_statement") or "").strip()
        if target_id in ids and statement:
            specific += 1
        key = (target_id, statement)
        if key not in seen:
            novel += 1
        seen.add(key)
    specificity = specific / n
    diversity = novel / n
    return {
        "specificity": round(specificity, 4),
        "target_diversity": round(diversity, 4),
        "structural_constructiveness": round((specificity + diversity) / 2, 4),
        "n_attacks": n,
    }


def evaluate_rubrics(log: dict[str, Any], evaluator_model: Any) -> dict[str, Any]:
    """1件のログを Constructiveness / Constraint Preservation（LLM）＋決定論的な構造指標で採点する.

    `build_eval_input` は1回だけ呼び、そこから transcript 用の入力と
    stance/final_answer 用の入力の両方を切り出す（整形ロジックの二重実装を避ける）。
    """
    eval_input = build_eval_input(log)
    constructiveness = evaluate_constructiveness(eval_input, evaluator_model)
    constraint_preservation = evaluate_constraint_preservation(eval_input, evaluator_model)
    structural = structural_constructiveness(log)
    return {
        "constructiveness": constructiveness.get("constructiveness"),
        "constraint_preservation": constraint_preservation.get("constraint_preservation"),
        "specificity": structural["specificity"],
        "target_diversity": structural["target_diversity"],
        "structural_constructiveness": structural["structural_constructiveness"],
        "evaluator_model": evaluator_model.model,
    }


# LLM 採点2軸に加えて保持する決定論的サブ指標（structural_constructiveness 系）。
_STRUCTURAL_KEYS = ("specificity", "target_diversity", "structural_constructiveness")


def build_metrics_v2(scores: dict[str, Any], efficiency: dict[str, Any]) -> dict[str, Any]:
    """新ルーブリック2軸 + 決定論的な構造指標 + 効率(time/cost/tokens) を1つの metrics dict にまとめる."""
    metrics = {axis: scores.get(axis) for axis in AXES_V2}
    numeric = [
        float(v) for a in AXES_V2 if isinstance((v := metrics.get(a)), (int, float))
    ]
    metrics["quality_average_v2"] = round(sum(numeric) / len(numeric), 2) if numeric else None
    # 決定論的サブ指標を落とさず持ち回る（schema/no_schema 以外は None のまま）。
    for key in _STRUCTURAL_KEYS:
        metrics[key] = scores.get(key)
    metrics.update(efficiency)
    metrics["evaluator_model"] = scores.get("evaluator_model", "unknown")
    return metrics


__all__ = [
    "AXES_V2",
    "CONSTRUCTIVENESS_INSTRUCTION",
    "CONSTRAINT_PRESERVATION_INSTRUCTION",
    "evaluate_constructiveness",
    "evaluate_constraint_preservation",
    "evaluate_rubrics",
    "build_metrics_v2",
    "build_eval_input",
    "efficiency_metrics",
]
