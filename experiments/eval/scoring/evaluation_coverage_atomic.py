"""stance文を依存構造解析で細分化した項目に基づくカバレッジ評価（evaluation_coverage.py の改良版）.

evaluation_coverage.py は stance の「You believe ...」の行をそのまま1項目として扱うため、
項目数が少数固定（各サイド3項目程度）になり、議論が実際に建設的かを問う前にスコアが
天井に張り付く問題があった。本モジュールは項目抽出だけを
`stance_decomposition.extract_stance_items_atomic`（spaCyの係り受け解析による機械的な
節分割、LLM不要・決定論的）に差し替え、判定ロジック（項目ごと独立LLM呼び出しでの
二値判定）は evaluation_coverage.py とそのまま同じものを再利用する。
"""

from __future__ import annotations

from typing import Any

from .evaluation_coverage import COVERAGE_INSTRUCTION, _parse_json_response
from .stance_decomposition import extract_stance_items_atomic


def evaluate_stance_coverage_atomic(
    log: dict[str, Any], evaluator_model: Any
) -> dict[str, Any]:
    """1件のログについて、細分化したスタンス項目のカバレッジ率を評価する.

    戻り値の形式は evaluation_coverage.evaluate_stance_coverage と同じ。
    """
    ag1_items = extract_stance_items_atomic(log.get("agent1_stance") or "")
    ag2_items = extract_stance_items_atomic(log.get("agent2_stance") or "")
    items = ag1_items + ag2_items
    final_answer = (log.get("final_answer") or "").strip()

    if not items:
        return {"covered": None, "total": 0, "ratio": None, "items": items, "addressed": None}
    if not final_answer:
        return {
            "covered": 0,
            "total": len(items),
            "ratio": 0.0,
            "items": items,
            "addressed": [False] * len(items),
        }

    addressed: list[bool | None] = []
    for item in items:
        prompt = COVERAGE_INSTRUCTION.format(item=item, final_answer=final_answer)
        try:
            raw = evaluator_model.invoke(prompt)
            parsed = _parse_json_response(raw)
            value = parsed.get("addressed")
            if not isinstance(value, bool):
                raise ValueError(f"expected bool, got: {value!r}")
            addressed.append(value)
        except Exception as e:  # noqa: BLE001 - 評価失敗を診断出力して継続する
            print(f"Atomic stance coverage evaluation failed for item {item[:60]!r}: {e}")  # noqa: T201
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


__all__ = ["evaluate_stance_coverage_atomic"]
