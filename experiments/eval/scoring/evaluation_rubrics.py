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

from experiments.eval.scoring.evaluation import build_eval_input, efficiency_metrics

AXES_V2 = ("constructiveness", "constraint_preservation")


CONSTRUCTIVENESS_INSTRUCTION = """
You are an evaluator LLM. Rate, on a scale from 1 to 10, how well the following debate
AVOIDS non-constructive responsive moves.

<evaluation_units>
A "responsive move" is either:
  1. an objection: a turn that challenges a conclusion, premise, or assumption from an
     earlier turn; or
  2. a revision: a new argument introduced after an earlier exchange has closed, where the
     speaker has an opportunity to adapt to the unresolved objection(s).

The first opening argument is context, not a responsive move. Narrator-style transition
notes and shared/integrated rules are context only; never score them as agent moves.

Infer response relations from semantic content and chronology even when a transcript does
not explicitly say "responding to". Do not reward or penalize a debate merely because its
format explicitly labels targets, premises, conclusions, or response links.
</evaluation_units>

<failure_modes>
Classify each responsive move as non-constructive if one or more of these applies:
  - TARGET MISMATCH: it ignores, misrepresents, or talks past the specific point it answers.
  - GENERIC RESPONSE: its reasoning could be used against almost any position on the topic
    and does not depend on the target's actual claim, premise, or assumption.
  - REPETITION: it substantially restates the speaker's own earlier position or reuses a
    point already raised and answered, without adapting it to the latest response.
  - NON-ADAPTIVE REVISION: after an exchange closes, the new argument repeats the failed
    argument without addressing the unresolved objection that led to the revision.

Merely quoting or naming a specific target is NOT enough. The move's supporting reason must
actually bear on that target and be used in reaching the response's conclusion. Conversely,
a move does not need to be novel, elaborate, or rhetorically impressive: a simple response
is constructive when it makes the minimum substantive adaptation needed to answer the
specific point.
</failure_modes>

<scope_boundaries>
Judge interactional responsiveness and non-redundancy only.
- Do NOT judge factual correctness, depth of evidence, rhetorical polish, grammar, verbosity,
  or which side wins. Those are separate qualities.
- Do NOT reward a structured format, explicit argument labels, or longer explanations.
- Do NOT penalize a debate merely for having more responsive moves. Use the PROPORTION and
  SEVERITY of non-constructive moves, not their raw count or transcript length.
</scope_boundaries>

<scoring>
First identify all responsive moves, then estimate the proportion that are non-constructive.
Use severity only to choose within the applicable band:
  9–10: 0–10% non-constructive.
  7–8:  More than 10% and up to 25% non-constructive.
  5–6:  More than 25% and up to 50% non-constructive.
  3–4:  More than 50% and up to 75% non-constructive.
  1–2:  More than 75% non-constructive.

If there are no responsive moves, assign 5 because there is insufficient interaction to
evaluate. Do the classification and proportion calculation silently; return only the JSON.
</scoring>

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


def evaluate_rubrics(log: dict[str, Any], evaluator_model: Any) -> dict[str, Any]:
    """1件のログを Constructiveness / Constraint Preservation（LLM）で採点する.

    Constructiveness には議論ターンだけを渡し、統合フェーズの生成物を混ぜない。
    Constraint Preservation には integrated_rules を含む入力を渡す。
    """
    constructiveness_input = build_eval_input(log, include_integrated_rules=False)
    constraint_input = build_eval_input(log)
    constructiveness = evaluate_constructiveness(
        constructiveness_input, evaluator_model
    )
    constraint_preservation = evaluate_constraint_preservation(
        constraint_input, evaluator_model
    )
    return {
        "constructiveness": constructiveness.get("constructiveness"),
        "constraint_preservation": constraint_preservation.get("constraint_preservation"),
        "evaluator_model": evaluator_model.model,
    }


def build_metrics_v2(scores: dict[str, Any], efficiency: dict[str, Any]) -> dict[str, Any]:
    """新ルーブリック2軸 + 効率(time/cost/tokens) を1つの metrics dict にまとめる."""
    metrics = {axis: scores.get(axis) for axis in AXES_V2}
    numeric = [
        float(v) for a in AXES_V2 if isinstance((v := metrics.get(a)), (int, float))
    ]
    metrics["quality_average_v2"] = round(sum(numeric) / len(numeric), 2) if numeric else None
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
