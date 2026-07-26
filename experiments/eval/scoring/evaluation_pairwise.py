"""ペア単位（対象の発言 + それへの1応答）でのローカル評価.

旧ルーブリック（Coherence/Originality/Dialecticality/Validity）は議論全体を1つの
transcript として渡し、holistic に採点していた。この設計だと、schema/no_schema
（main→defeat→counter→justified/overruled/defensible→新main…という分断的な
プロトコル）と mad/free_debate（分断のない連続討議）とで、そもそも evaluator に
見せている「1つの流れとしての読みやすさ」が違う可能性がある。

この違いを切り分けるため、議論全体ではなく「対象の発言 1つ + それへの直接の
応答 1つ」という最小単位のペアだけを evaluator に渡し、各ペアの建設性を独立に
採点してから平均する。

ペアの切り出し方は手法によって異なる:
- schema/no_schema: turn の target_id が指す相手の発言を対象とする（実際の
  弁証法的な参照関係）。
- mad/free_debate: 各ターンに target_id が無い（id を持たない）ため、直前の
  ターンを対象とみなす（プロトコル上、常に相手の直前の発言に反論する設計のため）。
"""

from __future__ import annotations

import json
from typing import Any

from experiments.eval.scoring.evaluation import _schema_utterance


def _turn_body_text(turn: dict[str, Any]) -> str:
    """1ターン分の発言本体（ラベルなし）をテキスト化する."""
    argument = turn.get("argument")
    if isinstance(argument, dict):
        body = argument.get("Argument")
        if isinstance(body, dict) and "rules" in body:
            return _schema_utterance(body, turn)
        return json.dumps(argument, ensure_ascii=False, indent=2)
    if isinstance(argument, str) and argument.strip():
        return argument.strip()
    return "(no argument)"


def extract_pairs(log: dict[str, Any]) -> list[dict[str, str]]:
    """ログから (target, response) のペアのリストを切り出す."""
    dialogue_history: list[dict[str, Any]] = log.get("dialogue_history") or []
    has_ids = any(isinstance(t.get("id"), str) for t in dialogue_history)

    pairs: list[dict[str, str]] = []
    if has_ids:
        id_to_turn = {
            t["id"]: t for t in dialogue_history if isinstance(t.get("id"), str)
        }
        for turn in dialogue_history:
            target_id = turn.get("target_id")
            if isinstance(target_id, str) and target_id in id_to_turn:
                pairs.append(
                    {
                        "target": _turn_body_text(id_to_turn[target_id]),
                        "response": _turn_body_text(turn),
                    }
                )
    else:
        for i in range(1, len(dialogue_history)):
            pairs.append(
                {
                    "target": _turn_body_text(dialogue_history[i - 1]),
                    "response": _turn_body_text(dialogue_history[i]),
                }
            )
    return pairs


PAIRWISE_CONSTRUCTIVENESS_INSTRUCTION = """
You are an evaluator LLM. You will see ONE claim from a dialectical debate (the
"Target") and ONE direct response to it (the "Response"). Rate, on a scale from
1 to 10, how CONSTRUCTIVE the Response is as a reply to the Target — judged in
isolation, without seeing the rest of the debate.

A constructive Response:
  - answers a specific claim, premise, or assumption actually stated in the Target; and
  - uses a supporting reason that actually bears on that target and is load-bearing for
    the Response's conclusion.

A non-constructive Response:
  - ignores, misrepresents, or talks past the Target;
  - gives generic reasoning that could be used against almost any position on the topic; or
  - merely quotes or names the Target before reasserting an unrelated position.

Do NOT judge factual correctness, depth of evidence, rhetorical polish, grammar, verbosity,
or structured formatting. Do NOT require novelty or elaborate reasoning when a simple,
specific response is sufficient. Because no earlier history is shown, do not infer whether
the Response repeats a still earlier turn.

Scoring rubric:
  9-10: Directly and substantively answers a specific point in the Target.
  7-8:  Answers a specific point, with a minor gap in how the reason bears on it.
  5-6:  Addresses the Target's general issue but not a specific stated point.
  3-4:  Mostly generic, misrepresents the Target, or largely talks past it.
  1-2:  Has no meaningful responsive relation to the Target.

Target:
{target}

Response:
{response}

Respond ONLY with a JSON object:
{{
  "pairwise_constructiveness": <int>,
  "evaluator_model": "<model name>"
}}
""".strip()


PAIRWISE_CONSTRUCTIVENESS_BATCH_INSTRUCTION = """
You are an evaluator LLM. Below are several independent (Target, Response) pairs
taken from one or more dialectical debates. Each pair is self-contained: judge
each pair ONLY against its own Target and Response, without letting any other
pair in this list influence your judgment of it.

For each pair, rate how CONSTRUCTIVE the Response is as a reply to the Target,
on a scale from 1 to 10.

A constructive Response:
  - answers a specific claim, premise, or assumption actually stated in its Target; and
  - uses a supporting reason that actually bears on that target and is load-bearing for
    the Response's conclusion.

A non-constructive Response:
  - ignores, misrepresents, or talks past its Target;
  - gives generic reasoning that could be used against almost any position on the topic; or
  - merely quotes or names its Target before reasserting an unrelated position.

Do NOT judge factual correctness, depth of evidence, rhetorical polish, grammar, verbosity,
or structured formatting. Do NOT require novelty or elaborate reasoning when a simple,
specific response is sufficient. Because no earlier history is shown, do not infer whether
a Response repeats a still earlier turn.

Scoring rubric:
  9-10: Directly and substantively answers a specific point in the Target.
  7-8:  Answers a specific point, with a minor gap in how the reason bears on it.
  5-6:  Addresses the Target's general issue but not a specific stated point.
  3-4:  Mostly generic, misrepresents the Target, or largely talks past it.
  1-2:  Has no meaningful responsive relation to the Target.

{pairs_block}

Respond ONLY with a JSON object containing exactly {n_pairs} scores, in the same
order as the pairs above:
{{
  "scores": [<int>, <int>, ...],
  "evaluator_model": "<model name>"
}}
""".strip()


def _format_pairs_block(pairs: list[dict[str, str]]) -> str:
    blocks = []
    for i, pair in enumerate(pairs, start=1):
        blocks.append(
            f"Pair {i}:\nTarget:\n{pair['target']}\n\nResponse:\n{pair['response']}"
        )
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


def evaluate_pair(pair: dict[str, str], evaluator_model: Any) -> int | None:
    """1ペア分を採点する."""
    prompt = PAIRWISE_CONSTRUCTIVENESS_INSTRUCTION.format(
        target=pair["target"], response=pair["response"]
    )
    try:
        raw = evaluator_model.invoke(prompt)
        result = _parse_json_response(raw, evaluator_model)
        score = result.get("pairwise_constructiveness")
        return int(score) if isinstance(score, (int, float)) else None
    except Exception as e:  # noqa: BLE001
        print(f"Pairwise evaluation failed: {e}")  # noqa: T201
        return None


def evaluate_pairwise_constructiveness(
    log: dict[str, Any], evaluator_model: Any
) -> dict[str, Any]:
    """ログ1件の全ペアを、1回のLLM呼び出しでまとめて採点する（ログ1件=API呼び出し1回）.

    各ペアは互いに独立に判定させたいが、ペア数だけ個別に呼び出すと通信回数が
    ログ件数の数倍に膨らむ（例: 平均5ペア/ログ x 1187ログ = 6401呼び出し）。
    プロンプト内で「他のペアに影響されず、各ペアをそれ単体で判定せよ」と明示した
    上で全ペアを1回のプロンプトにまとめ、スコアの配列を1回の応答で返させる。
    """
    pairs = extract_pairs(log)
    if not pairs:
        return {
            "pairwise_constructiveness": None,
            "pair_scores": [],
            "n_pairs": 0,
            "evaluator_model": evaluator_model.model,
        }
    prompt = PAIRWISE_CONSTRUCTIVENESS_BATCH_INSTRUCTION.format(
        pairs_block=_format_pairs_block(pairs), n_pairs=len(pairs)
    )
    try:
        raw = evaluator_model.invoke(prompt)
        result = _parse_json_response(raw, evaluator_model)
        scores = result.get("scores")
        if not isinstance(scores, list):
            scores = []
    except Exception as e:  # noqa: BLE001
        print(f"Pairwise batch evaluation failed: {e}")  # noqa: T201
        scores = []
    valid = [float(s) for s in scores if isinstance(s, (int, float))]
    return {
        "pairwise_constructiveness": round(sum(valid) / len(valid), 3)
        if valid
        else None,
        "pair_scores": scores,
        "n_pairs": len(pairs),
        "evaluator_model": evaluator_model.model,
    }


__all__ = [
    "extract_pairs",
    "PAIRWISE_CONSTRUCTIVENESS_INSTRUCTION",
    "PAIRWISE_CONSTRUCTIVENESS_BATCH_INSTRUCTION",
    "evaluate_pair",
    "evaluate_pairwise_constructiveness",
]
