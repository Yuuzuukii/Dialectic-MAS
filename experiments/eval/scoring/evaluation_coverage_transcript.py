"""stanceのatomic項目が議論トランスクリプト全体で提起されたかを評価する.

最終回答ではなくトランスクリプト全体のどこかで一度でも提起されたか
（transcript-level coverage）を見る。

evaluation_coverage_atomic.py の atomic coverage は final_answer だけを対象に
しており、「その論点が統合フェーズで拾われたか」を測る。これは「そもそも
論点が議論中に提起されたか」とは別の話で、two を混同すると、統合で拾い
損なうことが少ない手法（例: schema）が「論点をより多く生み出した」ように
見えてしまう恐れがある（実際に final_answer coverage ではそう見えた）。

本モジュールは同じ atomic 項目・同じ判定プロンプト構造を使いつつ、判定対象を
final_answer から debate_transcript（evaluation.build_eval_input が生成する、
4手法共通の統一フォーマット）に差し替えることで、「論点がそもそも議論の中で
出たか」だけを独立に測る。
"""

from __future__ import annotations

from typing import Any

from .evaluation import build_eval_input
from .evaluation_coverage import _parse_json_response
from .stance_decomposition import extract_stance_items_atomic

TRANSCRIPT_COVERAGE_INSTRUCTION = """
You are an evaluator LLM. Judge whether the claim below was raised anywhere in
the debate transcript (by either speaker, at any point) — not whether it was
resolved or agreed upon, just whether it was raised as a point of discussion.

Raised: the transcript engages with the claim's specific substance somewhere
(states it, argues for/against it, or directly responds to it).

Not raised: the transcript never brings up this claim's substance at all.

Claim:
{item}

Debate Transcript:
{transcript}

Respond ONLY with a JSON object: {{"raised": <bool>}}
""".strip()


def evaluate_stance_coverage_transcript(
    log: dict[str, Any], evaluator_model: Any
) -> dict[str, Any]:
    """1件のログについて、細分化したスタンス項目が議論全体で提起されたかの率を評価する.

    戻り値の形式は evaluation_coverage_atomic.evaluate_stance_coverage_atomic と同じ
    （key名だけ "raised" 相当を "covered"/"addressed" に揃える）。
    """
    ag1_items = extract_stance_items_atomic(log.get("agent1_stance") or "")
    ag2_items = extract_stance_items_atomic(log.get("agent2_stance") or "")
    items = ag1_items + ag2_items

    eval_input = build_eval_input(log)
    transcript = eval_input["debate_transcript"]

    if not items:
        return {"covered": None, "total": 0, "ratio": None, "items": items, "addressed": None}
    if transcript == "(no dialogue)":
        return {
            "covered": 0,
            "total": len(items),
            "ratio": 0.0,
            "items": items,
            "addressed": [False] * len(items),
        }

    addressed: list[bool | None] = []
    for item in items:
        prompt = TRANSCRIPT_COVERAGE_INSTRUCTION.format(item=item, transcript=transcript)
        try:
            raw = evaluator_model.invoke(prompt)
            parsed = _parse_json_response(raw)
            value = parsed.get("raised")
            if not isinstance(value, bool):
                raise ValueError(f"expected bool, got: {value!r}")
            addressed.append(value)
        except Exception as e:  # noqa: BLE001 - 評価失敗を診断出力して継続する
            print(f"Transcript coverage evaluation failed for item {item[:60]!r}: {e}")  # noqa: T201
            addressed.append(None)

    valid = [a for a in addressed if isinstance(a, bool)]
    if not valid:
        return {"covered": None, "total": len(items), "ratio": None, "items": items, "addressed": addressed}
    covered = sum(1 for a in valid if a)
    return {
        "covered": covered,
        "total": len(items),
        "ratio": covered / len(items),
        "items": items,
        "addressed": addressed,
    }


__all__ = ["TRANSCRIPT_COVERAGE_INSTRUCTION", "evaluate_stance_coverage_transcript"]
