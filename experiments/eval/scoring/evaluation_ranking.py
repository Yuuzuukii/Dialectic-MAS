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

Rank the {n} debates from MOST to LEAST constructive, judging the exchange of
objections in each debate transcript in isolation (do not let one debate's
labeling or position influence your judgment of another).

Constructiveness means each objection in a transcript avoids non-constructive
exchange and instead advances the debate. Judge each objection (rebut/undercut/
counter turn) against these failure modes:
  - Repeats the objecting side's own prior claim essentially unchanged, without
    engaging the specific point it targets.
  - Is a generic or vague rebuttal that could apply to almost any claim, rather
    than engaging the specific claim or assumption actually made by the target.
  - Ignores or talks past the target's specific point (a non-sequitur relative
    to what was actually said).
  - Restates a point that was already raised and answered earlier in the
    transcript, without adding new reasoning.

A high-constructiveness debate is one where every objection engages a specific
point with new reasoning, so the exchange visibly narrows or sharpens over
time. A low-constructiveness debate is dominated by circular restatement,
generic rebuttals, or turns that talk past each other.

IMPORTANT: You must produce a strict total ranking (no ties). Base the ranking
only on constructiveness as defined above, not on which side "wins" the debate.

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


__all__ = ["RANKING_INSTRUCTION", "rank_debates"]
