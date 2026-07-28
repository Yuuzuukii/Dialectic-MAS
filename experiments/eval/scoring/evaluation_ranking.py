"""同一トピックについて4手法の議論を1つのプロンプトにまとめ、順位をつけさせる評価.

絶対スコア（1〜10）の holistic/pairwise 評価はスケールのブレ（同一内容の再評価でも
評価者内でブレる）に晒される。同じトピックの4手法分の議論を並べて相対順位を
つけさせれば、評価者内の採点基準は1回の判断で揃うため、絶対スコアより頑健な
比較になりうる。

手法名は見せず、ランダムな順序でラベル（A/B/C/D）を割り当てて渡す（手法名を
見せると事前知識でバイアスがかかるため）。渡す議論本体は
`evaluation.build_eval_input(log, include_integrated_rules=False)` の
`debate_transcript`（統合ルール・最終回答を含まない、議論部分のみ）を使う。
"""

from __future__ import annotations

import json
import random
from typing import Any

from experiments.eval.scoring.evaluation import build_eval_input

RANKING_INSTRUCTION = """
You are an evaluator LLM. Below are {n} independent debates, all addressing the
SAME question from the SAME two stances, produced by different (unlabeled)
methods. Each is labeled with a letter (A, B, C, ...).

Rank the {n} debates from MOST to LEAST constructive. Judge each transcript in
isolation before comparing them.

<evaluation_units>
A "responsive move" is either:
  1. an objection that challenges an earlier conclusion, premise, or assumption; or
  2. a new argument introduced after an earlier exchange has closed, where the speaker
     has an opportunity to adapt to unresolved objections.

The first opening argument is context. Narrator-style transition notes and shared rules
are context only. Infer response relations from content and chronology even if they are
not explicitly labeled.
</evaluation_units>

<failure_modes>
A responsive move is non-constructive when it:
  - ignores, misrepresents, or talks past the specific point it answers;
  - gives generic reasoning that does not depend on the target's actual content;
  - substantially repeats the speaker's earlier position or a point already answered,
    without adapting it to the latest response; or
  - introduces a revised argument after an exchange closes but fails to address the
    unresolved objection that made revision necessary.

Merely quoting a target is not sufficient: the supporting reason must actually bear on
that target and be used in reaching the response's conclusion. A response need not be
novel or elaborate when a simple, specific adaptation is sufficient.
</failure_modes>

<comparison_rules>
- Compare the PROPORTION and SEVERITY of non-constructive responsive moves, not their
  raw count. Do not penalize a debate merely because it is longer.
- Judge semantic interaction only. Do not reward explicit labels, structured formatting,
  rhetorical polish, verbosity, factual sophistication, or which side wins.
- If two debates have the same failure proportion, prefer the one with less severe
  failures, then the one whose later moves adapt more directly to unresolved objections.
</comparison_rules>

IMPORTANT: Produce a strict total ranking with no ties.

Question:
{question}

AG1 Stance:
{agent1_stance}

AG2 Stance:
{agent2_stance}

{debates_block}

Respond ONLY with a JSON object:
{{
  "ranking": ["<letter of most constructive>", "...", "<letter of least constructive>"],
  "evaluator_model": "<model name>"
}}
""".strip()


def _format_debates_block(labeled_transcripts: list[tuple[str, str]]) -> str:
    blocks = []
    for label, transcript in labeled_transcripts:
        blocks.append(f"Debate {label}:\n{transcript}")
    return "\n\n".join(blocks)


def _parse_json_response(raw: str, evaluator_model: Any) -> dict[str, Any]:
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


def rank_debates(
    logs_by_method: dict[str, dict[str, Any]],
    evaluator_model: Any,
    *,
    rng: random.Random | None = None,
) -> dict[str, Any]:
    """同一トピックの複数手法のログを1回の呼び出しでランキングする.

    `logs_by_method`: {method_name: log_dict, ...}（同一トピック・同一 question/stance
    であることが前提）。
    戻り値: {method_name: rank (1が最も建設的), ...} を含む dict。
    """
    rng = rng or random.Random()
    methods = list(logs_by_method.keys())
    rng.shuffle(methods)  # 提示順を毎回ランダム化し、位置バイアスを避ける
    letters = [chr(ord("A") + i) for i in range(len(methods))]
    label_to_method = dict(zip(letters, methods))

    eval_inputs = {
        m: build_eval_input(logs_by_method[m], include_integrated_rules=False)
        for m in methods
    }
    # question/stance は全手法で共通のはず。念のため最初のものを使う。
    first = eval_inputs[methods[0]]

    labeled_transcripts = [
        (label, eval_inputs[label_to_method[label]]["debate_transcript"])
        for label in letters
    ]

    prompt = RANKING_INSTRUCTION.format(
        n=len(methods),
        question=first["question"],
        agent1_stance=first["agent1_stance"],
        agent2_stance=first["agent2_stance"],
        debates_block=_format_debates_block(labeled_transcripts),
    )

    try:
        raw = evaluator_model.invoke(prompt)
        result = _parse_json_response(raw, evaluator_model)
        ranking = result.get("ranking")
        if not isinstance(ranking, list):
            ranking = []
    except Exception as e:  # noqa: BLE001
        print(f"Ranking evaluation failed: {e}")  # noqa: T201
        ranking = []

    method_rank: dict[str, int | None] = {m: None for m in methods}
    for position, label in enumerate(ranking, start=1):
        method = label_to_method.get(label)
        if method is not None and method_rank.get(method) is None:
            method_rank[method] = position

    return {
        "method_rank": method_rank,
        "label_to_method": label_to_method,
        "raw_ranking": ranking,
        "evaluator_model": evaluator_model.model,
    }


CONSTRAINT_PRESERVATION_RANKING_INSTRUCTION = """
You are an evaluator LLM. Below are {n} independent final answers to the SAME question,
written for the SAME two stances, produced by different (unlabeled) methods. Each is
labeled with a letter (A, B, C, ...). You are NOT shown the debate that produced them.

Rank the {n} final answers from BEST to WORST at preserving the constraints and
requirements presented in each side's stance.

<criteria>
Judge only whether each final answer, read against the two stances, respects the
specific constraints, conditions, and requirements each side raised — either by
explicitly satisfying/addressing them, or by taking a position that a reasonable
reading of both stances would still endorse — rather than silently dropping one side's
requirements in favor of a generic compromise or an unqualified endorsement of only one
side.

Penalize an answer that:
  - ignores a specific, substantive requirement or condition named in one side's stance
    (e.g. a named threshold, exception, or precondition) without acknowledging it;
  - resolves the disagreement with a generic compromise that doesn't engage with the
    specific substance either side raised;
  - adopts one side's position wholesale while leaving the other side's stated
    requirements completely unaddressed.

Reward an answer that names the specific constraints/requirements from both stances and
shows how it accounts for them (satisfies, qualifies, or explains why one is
overridden), reaching a position that could not be reached without taking both sides'
specific requirements into account.
</criteria>

IMPORTANT: Produce a strict total ranking with no ties.

Question:
{question}

AG1 Stance:
{agent1_stance}

AG2 Stance:
{agent2_stance}

{answers_block}

Respond ONLY with a JSON object:
{{
  "ranking": ["<letter of best>", "...", "<letter of worst>"],
  "evaluator_model": "<model name>"
}}
""".strip()


def _format_answers_block(labeled_answers: list[tuple[str, str]]) -> str:
    blocks = []
    for label, answer in labeled_answers:
        blocks.append(f"Final Answer {label}:\n{answer}")
    return "\n\n".join(blocks)


def rank_final_answers_by_constraint_preservation(
    logs_by_key: dict[str, dict[str, Any]],
    evaluator_model: Any,
    *,
    rng: random.Random | None = None,
) -> dict[str, Any]:
    """同一トピックの複数候補の最終回答を、constraint_preservation の観点からランキングする.

    複数候補は手法違い、または同一手法の設定違いのどちらでもよい。
    `rank_debates` は debate_transcript（議論部分）を比較するのに対し、こちらは
    final_answer だけを比較する（constraint_preservation の採点自体が transcript を
    見ないのと同じ入力設計）。

    `logs_by_key`: {key: log_dict, ...}（同一トピック・同一 question/stance が前提。
    key はmethod名でも `attempts01`のような設定名でも良い）。
    戻り値: {key: rank (1が最も要件を保持), ...} を含む dict。
    """
    rng = rng or random.Random()
    keys = list(logs_by_key.keys())
    rng.shuffle(keys)  # 提示順を毎回ランダム化し、位置バイアスを避ける
    letters = [chr(ord("A") + i) for i in range(len(keys))]
    label_to_key = dict(zip(letters, keys))

    eval_inputs = {k: build_eval_input(logs_by_key[k]) for k in keys}
    first = eval_inputs[keys[0]]

    labeled_answers = [
        (label, eval_inputs[label_to_key[label]]["final_answer"]) for label in letters
    ]

    prompt = CONSTRAINT_PRESERVATION_RANKING_INSTRUCTION.format(
        n=len(keys),
        question=first["question"],
        agent1_stance=first["agent1_stance"],
        agent2_stance=first["agent2_stance"],
        answers_block=_format_answers_block(labeled_answers),
    )

    try:
        raw = evaluator_model.invoke(prompt)
        result = _parse_json_response(raw, evaluator_model)
        ranking = result.get("ranking")
        if not isinstance(ranking, list):
            ranking = []
    except Exception as e:  # noqa: BLE001
        print(f"Constraint-preservation ranking evaluation failed: {e}")  # noqa: T201
        ranking = []

    key_rank: dict[str, int | None] = {k: None for k in keys}
    for position, label in enumerate(ranking, start=1):
        key = label_to_key.get(label)
        if key is not None and key_rank.get(key) is None:
            key_rank[key] = position

    return {
        "key_rank": key_rank,
        "label_to_key": label_to_key,
        "raw_ranking": ranking,
        "evaluator_model": evaluator_model.model,
    }


__all__ = [
    "RANKING_INSTRUCTION",
    "CONSTRAINT_PRESERVATION_RANKING_INSTRUCTION",
    "rank_debates",
    "rank_final_answers_by_constraint_preservation",
]
