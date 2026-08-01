"""スタンス項目のカバレッジ率（最終回答にどれだけ反映されているか）による評価.

holistic な 1〜10 スコア（evaluation_rubrics.py の constraint_preservation）は
評価者内でのブレが大きい。この指標は、より分解された・再現性の高い代替として:

1. スタンス文（agent1_stance / agent2_stance）から主張項目を機械的に切り出す
   （LLM不要。データセットのstanceは "Your stance:" ヘッダー行 + 立場表明1行 +
   "You believe ..." が1項目1行、という一貫したフォーマットのため、先頭2行を
   除いた残りの行がそのまま項目になる）。
2. 項目ごとに**独立したLLM呼び出し**で「最終回答で扱われているか」を yes/no判定する
   （全項目をまとめて1回で判定させると、項目数が多いほど後半の項目への注意が
   薄れたり、全体のバランスを取ろうとして判定が歪んだりするリスクがあるため。
   コストは項目数倍になるが、1呼び出しあたりの判断はシンプルになる）。
3. カバレッジ率 = 扱われている項目数 / 総項目数。

項目の総数はスタンス文が固定である限り決定論的（毎回同じ値）。ブレうるのは
「反映されているか」の判定だけで、そこも1個の総合スコアではなく項目ごと・
呼び出しごとの独立した二値判定にすることで、holisticな採点よりブレを抑える狙い。
"""

from __future__ import annotations

import json
from typing import Any


def extract_stance_items(stance: str) -> list[str]:
    """stance文字列から主張項目（"You believe ..."の行）を機械的に抽出する.

    データセットの stance は
      Your stance:
      You support/oppose X.
      You believe ... .
      You believe ... .
      ...
    という固定フォーマット。先頭2行（ヘッダーと立場表明）を除いた残りを項目とする。
    """
    lines = [line.strip() for line in (stance or "").splitlines() if line.strip()]
    return lines[2:] if len(lines) > 2 else []


COVERAGE_INSTRUCTION = """
You are an evaluator LLM. Judge whether the final answer addresses the claim below.

Addressed: the final answer engages with the claim's specific substance (satisfies it,
qualifies it, or explains why it's overridden).

Not addressed: the final answer is silent on the claim, or only generically consistent
with it without engaging its substance.

Claim:
{item}

Final Answer:
{final_answer}

Respond ONLY with a JSON object: {{"addressed": <bool>}}
""".strip()


def _parse_json_response(raw: str) -> dict[str, Any]:
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
    return result


def evaluate_stance_coverage(
    log: dict[str, Any], evaluator_model: Any
) -> dict[str, Any]:
    """1件のログについて、スタンス項目のカバレッジ率を評価する.

    戻り値: {"covered": int|None, "total": int, "ratio": float|None,
             "items": list[str], "addressed": list[bool]|None}
    final_answer が無い、または項目が無い場合は ratio=None（評価不能）。
    """
    ag1_items = extract_stance_items(log.get("agent1_stance") or "")
    ag2_items = extract_stance_items(log.get("agent2_stance") or "")
    items = ag1_items + ag2_items
    final_answer = (log.get("final_answer") or "").strip()

    if not items:
        return {
            "covered": None,
            "total": 0,
            "ratio": None,
            "items": items,
            "addressed": None,
        }
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
            print(f"Stance coverage evaluation failed for item {item[:60]!r}: {e}")  # noqa: T201
            addressed.append(None)

    valid = [a for a in addressed if isinstance(a, bool)]
    if not valid:
        return {
            "covered": None,
            "total": len(items),
            "ratio": None,
            "items": items,
            "addressed": addressed,
        }
    covered = sum(1 for a in valid if a)
    return {
        "covered": covered,
        "total": len(items),
        "ratio": covered / len(items),
        "items": items,
        "addressed": addressed,
    }


__all__ = [
    "COVERAGE_INSTRUCTION",
    "extract_stance_items",
    "evaluate_stance_coverage",
]
