"""最終回答に対する「文句(objection)」の有無による評価.

第三者の評価者LLMに判定させるのではなく、実際に議論していた本人（Agent1 /
Agent2）の人格（stance）にそのまま議論の全体（debate_transcript）と最終回答を
見せ、一人称で「あなたはこの最終回答に文句があるか」を yes/no で判定させる。

当初はstance + final_answerだけ（議論履歴なし）で判定していたが、それだと
「最終回答の文面がヘッジ表現（'does not, by itself, overturn' のような留保付き
の書き方）かどうか」に判定が引っ張られ、実際には議論中にすでに扱われていた
反論でも、最終回答の書きぶり次第で「まだ反論できる」と判定されてしまう問題が
あった。ここでは debate_transcript（evaluation.build_eval_input が生成する、
schema/no_schema/free_debate/mad 共通の統一フォーマット）も見せた上で、
「議論全体を踏まえてなお有効な（＝すでに議論中で扱われていない）反論を
出せるか」を問うことで、最終回答単体の文体に判定が引きずられるのを抑える。

外部評価者が「この立場の人物ならこう思うだろう」と代弁する形（third-person
judge）ではなく、その立場を実際に演じていたエージェント自身に一人称で答え
させる（first-person self-report）ことで、代弁による解釈のブレを避ける。

atomic coverage（項目が言及されたか）とは異なる軸で、「統合された結論に
両者とも実際に納得できるか」を直接問う指標。
"""

from __future__ import annotations

from typing import Any

from .evaluation import build_eval_input
from .evaluation_coverage import _parse_json_response

OBJECTION_INSTRUCTION = """
<identity>
You are {agent} in a debate. Below is your own stance, the full debate
transcript (including both your own and your opponent's turns), and the
final answer that was reached to resolve the disagreement.
</identity>

Your stance:
{stance}

Debate transcript:
{transcript}

Final Answer:
{final_answer}

This final answer comes down on one side of the issue. Having seen the whole
debate, even where the final answer differs from your own stance, could you
accept it — or can you still raise a VALID objection against it, as {agent}?
An objection only counts if it was not already raised and addressed during
the debate above.

Respond ONLY with a JSON object: {{"has_objection": <bool>, "reason": "<one short sentence, in your own voice>"}}
""".strip()


def _judge_one(
    agent: str, stance: str, transcript: str, final_answer: str, judge_model: Any
) -> dict[str, Any]:
    prompt = OBJECTION_INSTRUCTION.format(
        agent=agent, stance=stance, transcript=transcript, final_answer=final_answer
    )
    try:
        raw = judge_model.invoke(prompt)
        parsed = _parse_json_response(raw)
        value = parsed.get("has_objection")
        if not isinstance(value, bool):
            raise ValueError(f"expected bool, got: {value!r}")
        return {"has_objection": value, "reason": parsed.get("reason")}
    except Exception as e:  # noqa: BLE001 - 評価失敗を診断出力して継続する
        print(f"Objection evaluation failed: {e}")  # noqa: T201
        return {"has_objection": None, "reason": None}


def evaluate_final_answer_objections(
    log: dict[str, Any], judge_model: Any
) -> dict[str, Any]:
    """1件のログについて、両エージェント本人による最終回答への文句の有無を評価する.

    戻り値: {
        "agent1": {"has_objection": bool|None, "reason": str|None},
        "agent2": {"has_objection": bool|None, "reason": str|None},
        "any_objection": bool|None,  # どちらか一方でも文句があれば True
    }
    """
    eval_input = build_eval_input(log)
    final_answer = eval_input["final_answer"]
    transcript = eval_input["debate_transcript"]
    ag1_stance = eval_input["agent1_stance"]
    ag2_stance = eval_input["agent2_stance"]

    if (
        final_answer == "(no final answer)"
        or ag1_stance == "(not provided)"
        or ag2_stance == "(not provided)"
    ):
        empty = {"has_objection": None, "reason": None}
        return {"agent1": empty, "agent2": empty, "any_objection": None}

    ag1_result = _judge_one("AG1", ag1_stance, transcript, final_answer, judge_model)
    ag2_result = _judge_one("AG2", ag2_stance, transcript, final_answer, judge_model)

    flags = [
        r["has_objection"]
        for r in (ag1_result, ag2_result)
        if isinstance(r["has_objection"], bool)
    ]
    any_objection = any(flags) if flags else None

    return {"agent1": ag1_result, "agent2": ag2_result, "any_objection": any_objection}


__all__ = ["OBJECTION_INSTRUCTION", "evaluate_final_answer_objections"]
