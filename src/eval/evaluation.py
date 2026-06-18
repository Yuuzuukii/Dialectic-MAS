"""LLM 評価用の入力整形・効率指標・スコア集計・LLM 採点を行うヘルパ群."""

from __future__ import annotations

import json
from typing import Any, cast


def _parse_argument_field(argument_str: str | Any) -> dict[str, Any]:
    if not isinstance(argument_str, str):
        if isinstance(argument_str, dict):
            return argument_str
        return {}
    text = argument_str.strip()
    if "```json" in text:
        start = text.find("```json") + len("```json")
        text = text[start: text.find("```", start)].strip()
    elif text.startswith("```"):
        text = text[3: text.rfind("```")].strip()
    else:
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            text = text[start:end]
    try:
        return cast(dict[str, Any], json.loads(text))
    except (json.JSONDecodeError, ValueError):
        return {}


def _extract_conc(argument_str: str | Any) -> list[str]:
    parsed = _parse_argument_field(argument_str)
    body = parsed.get("Argument", parsed)
    conc = body.get("Conc", [])
    return [c for c in conc if isinstance(c, str) and c.strip()]


def _format_turn(argument: Any) -> str:
    """1 ターン分の発話 (argument) を評価器向けの読みやすいテキストに整形する.

    schema: {"Argument": {"rules": [...], "Conc": [...], "Ass": [...]}} 形式の dict。
    no_schema: 自由記述の文字列。
    """
    if isinstance(argument, str):
        text = argument.strip()
        return text if text else "(no argument)"

    if not isinstance(argument, dict):
        return "(no argument)"

    body = argument.get("Argument", argument)
    if not isinstance(body, dict):
        return "(no argument)"

    lines: list[str] = []
    rules = body.get("rules") or []
    for i, rule in enumerate(rules, 1):
        if not isinstance(rule, dict):
            continue
        antecedent = rule.get("antecedent") or {}
        strong = antecedent.get("strong") or []
        weak = antecedent.get("weak_negation") or []
        lines.append(f"  Rule {i}:")
        for premise in strong:
            lines.append(f"    - {premise}")
        for assumption in weak:
            lines.append(f"    - (assumption) {assumption}")
        consequent = rule.get("consequent")
        if consequent:
            lines.append(f"    => {consequent}")

    conc = _extract_conc(argument)
    if conc:
        lines.append("  Conclusion: " + "; ".join(conc))

    return "\n".join(lines) if lines else "(no argument)"


def build_eval_input(log: dict[str, Any], *, mode: str = "schema") -> dict[str, Any]:
    """実行ログを、LLM 評価器へ渡す入力 dict に整形する.

    ログは question / agent1_stance / agent2_stance / dialogue_history
    (各ターンの {agent, argument}) / final_answer / metrics のみを持つ。
    schema / no_schema は argument の表現形式（構造化 JSON か自由記述テキストか）が
    異なるだけで、整形ロジックは共通。`mode` に応じて method_context だけ切り替える。
    """
    dialogue_history: list[dict[str, Any]] = log.get("dialogue_history") or []

    transcript_lines = [
        f"[Turn {i}] {record.get('agent', '?')}:\n{_format_turn(record.get('argument'))}"
        for i, record in enumerate(dialogue_history, start=1)
    ]

    final_answer = log.get("final_answer")
    final_answer_text = final_answer.strip() if isinstance(final_answer, str) and final_answer.strip() else "(no final answer)"

    return {
        "mode": mode,
        "method_context": SCHEMA_METHOD_CONTEXT if mode == "schema" else NO_SCHEMA_METHOD_CONTEXT,
        "question": log.get("question", ""),
        "agent1_stance": log.get("agent1_stance") or "(not provided)",
        "agent2_stance": log.get("agent2_stance") or "(not provided)",
        "debate_transcript": "\n\n".join(transcript_lines) if transcript_lines else "(no dialogue)",
        "final_answer": final_answer_text,
    }


AXES = ("coherence", "originality", "dialecticality", "validity")


def efficiency_metrics(log: dict[str, Any]) -> dict[str, Any]:
    """ログの metrics から効率指標（時間・コスト・トークン）を取り出す（LLM 採点ではない）."""
    metrics = log.get("metrics", {}) or {}
    return {
        "elapsed_seconds": metrics.get("elapsed_seconds"),
        "total_cost_usd": metrics.get("total_cost_usd"),
        "total_tokens": metrics.get("total_tokens"),
    }


def aggregate_scores(scores: list[dict[str, Any]]) -> dict[str, Any]:
    """複数スコア dict を軸ごとに平均し、全軸平均 (average) と件数 (n) を付与する."""
    agg: dict[str, Any] = {}
    for axis in AXES:
        nums: list[float] = [
            float(s[axis]) for s in scores if isinstance(s.get(axis), (int, float))
        ]
        agg[axis] = round(sum(nums) / len(nums), 2) if nums else None
    axis_vals: list[float] = [agg[a] for a in AXES if isinstance(agg[a], (int, float))]
    agg["average"] = round(sum(axis_vals) / len(axis_vals), 2) if axis_vals else None
    agg["n"] = len(scores)
    return agg


COMMON_EVALUATION_CONTEXT = """
You are evaluating a multi-agent dialogue between AG1 and AG2.

Both agents have fixed stances. The debate transcript below lists each agent's turns in chronological
order (labeled "[Turn N] AGENT:"); turns alternate roughly as: each agent states a main argument for
its stance, the opponent attacks it (rebutting its conclusion or undercutting an assumption it relies
on), the original agent defends or counters, and so on. Once both sides' reasoning is exhausted, the
agents extract and integrate shared rules from the debate and produce a final answer.

Judge whether the dialogue produces a coherent, useful, and fair final position from the information
shown below. Use the method-specific context only to interpret the argument format; do not reward or
penalize a run merely because it uses, or does not use, a formal schema.
""".strip()

SCHEMA_METHOD_CONTEXT = """
This run uses the proposed schema-based dialectical method, based on ASPIC+-style argumentation.

--- Argument Format ---
Each turn's argument is a sequence of rules. A rule has:
  - Premises:    Established premises (must hold for the rule to fire), and any premises marked
                 "(assumption)" are defeasible assumptions that an opponent may attack by undercut.
  - Conclusion:  The conclusion derived from the premises ("=>").
A turn may also list its overall "Conclusion" — the conclusion(s) it ultimately puts forward.

--- Attacks ---
  - rebut:    An agent's argument explicitly negates a conclusion of the target argument.
              (direct clash of conclusions)
  - undercut: An agent's argument explicitly negates an assumption the target argument relies on.
              (attacks a defeasible assumption the target relies on)
""".strip()

NO_SCHEMA_METHOD_CONTEXT = """
This run uses the same dialectical protocol and dialogue flow as the schema-based method (see below),
but each agent's argument is expressed as free natural-language reasoning instead of a structured
rules/Conclusion representation.

--- Attacks ---
  - rebut:    An agent's argument explicitly negates the target argument's stated conclusion.
              (direct clash of conclusions)
  - undercut: An agent's argument explicitly negates an assumption the target argument relies on.
              (attacks a defeasible assumption the target relies on)
""".strip()

SCORING_INSTRUCTION = """
Rate the above dialectical reasoning on a scale from 1 to 10 for each of the following:

1. Coherence      – Does the final synthesis follow logically from the initial opinion and counterarguments?
2. Originality    – Does the synthesis demonstrate novel insight, creative framing, or non-obvious conclusions?
3. Dialecticality – Does the response meaningfully integrate both perspectives, showing fair reasoning and synthesis?
4. Validity       – Are the method's own dialectical commitments sound when re-examined from each agent's stance?
                    Check whether each turn's attacks (rebut/undercut) and counters genuinely target the
                    conclusions or assumptions they claim to, and whether the final answer is fairly warranted
                    by the transcript and both agents' stances. A high score means the debate closes or
                    synthesizes for good reasons; a low score means important stance-consistent objections
                    were mishandled, ignored, or unsupported.

Scoring rubric:
  9–10: Outstanding – excellent quality for the axis
  7–8:  Good – solid, with minor issues
  5–6:  Adequate – average quality, some issues
  1–4:  Weak – lacking clarity, logic, originality, validity, or synthesis

IMPORTANT: Rate strictly. Perfect scores are rare.

Respond ONLY with a JSON object:
{
  "coherence": <int>,
  "originality": <int>,
  "dialecticality": <int>,
  "validity": <int>,
  "evaluator_model": "<model name>"
}
""".strip()


def evaluate_with_llm(response: dict[str, Any], evaluator_model: Any) -> dict[str, Any]:
    """Evaluate a Dialect-MAS run using an LLM as evaluator.

    `response` should be the output of build_eval_input().
    `evaluator_model` must expose .model (str) and .invoke(prompt: str) -> str.
    Returns a dict with numeric scores and model info.
    """
    prompt = f"""
{COMMON_EVALUATION_CONTEXT}

--- Method Context ---
Mode: {response['mode']}

{response['method_context']}

--- Debate to Evaluate ---

Question:
{response['question']}

AG1 Stance:
{response['agent1_stance']}

AG2 Stance:
{response['agent2_stance']}

Debate Transcript (chronological, each turn is one agent's argument):
{response['debate_transcript']}

Final Answer:
{response['final_answer']}

---

{SCORING_INSTRUCTION}
""".strip()

    try:
        raw: str = evaluator_model.invoke(prompt)
        text = raw.strip()
        if "```json" in text:
            start = text.find("```json") + len("```json")
            text = text[start: text.find("```", start)].strip()
        elif text.startswith("```"):
            text = text[3: text.rfind("```")].strip()
        else:
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                text = text[start:end]
        scores: dict[str, Any] = json.loads(text)
        scores["evaluator_model"] = evaluator_model.model
        return scores
    except Exception as e:
        print(f"Evaluation failed: {e}")  # noqa: T201  # 評価失敗を端末へ知らせる診断出力。
        return {
            "coherence": None,
            "originality": None,
            "dialecticality": None,
            "validity": None,
            "evaluator_model": getattr(evaluator_model, "model", "unknown"),
        }
