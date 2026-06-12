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


def _extract_ass(argument_str: str | Any) -> list[str]:
    parsed = _parse_argument_field(argument_str)
    body = parsed.get("Argument", parsed)
    ass = body.get("Ass", [])
    if ass:
        return [a for a in ass if isinstance(a, str) and a.strip()]
    rules = body.get("rules", [])
    result: list[str] = []
    for rule in rules:
        if isinstance(rule, dict) and isinstance(rule.get("antecedent"), dict):
            result.extend(
                a for a in rule["antecedent"].get("weak_negation", [])
                if isinstance(a, str) and a.strip()
            )
    return result


def build_eval_input(log: dict[str, Any]) -> dict[str, Any]:
    """スキーマ版の実行ログを、LLM 評価器へ渡す入力 dict に整形する."""
    question = log.get("question", "")
    dialogue_history: list[dict[str, Any]] = log.get("dialogue_history", [])
    integrated_rules: list[str] = log.get("integrated_rules") or []
    justification_status: str = log.get("justification_status") or ""

    ag1_mains: list[str] = []
    ag2_mains: list[str] = []
    debate_lines: list[str] = []

    for record in dialogue_history:
        rtype = record.get("type", "")
        agent = record.get("agent", "")
        argument_str = record.get("argument", "")
        conc = _extract_conc(argument_str)
        ass = _extract_ass(argument_str)

        if rtype == "main":
            text = "; ".join(conc) if conc else "(no conclusion)"
            if agent == "AG1":
                ag1_mains.append(text)
            elif agent == "AG2":
                ag2_mains.append(text)
        elif rtype in {"defeat", "counter"}:
            attack = record.get("attack") or "—"
            target_id = record.get("target_id") or "—"
            conc_text = "; ".join(conc) if conc else "(no conclusion)"
            ass_text = "; ".join(ass) if ass else "none"
            debate_lines.append(
                f"[{rtype}] {agent} (attack: {attack}, target: {target_id})\n"
                f"  Conc: {conc_text}\n"
                f"  Ass:  {ass_text}"
            )

    justified_raw = log.get("justified_argument")
    justified_conc = _extract_conc(justified_raw)
    justified_text = "; ".join(justified_conc) if justified_conc else "(no conclusion)"

    return {
        "mode": "schema",
        "method_context": SCHEMA_METHOD_CONTEXT,
        "question": question,
        "agent1_stance": log.get("agent1_stance") or "(not provided)",
        "agent2_stance": log.get("agent2_stance") or "(not provided)",
        "ag1_initial_opinion": "\n".join(ag1_mains) if ag1_mains else "(none)",
        "ag2_initial_opinion": "\n".join(ag2_mains) if ag2_mains else "(none)",
        "debate_history": "\n\n".join(debate_lines) if debate_lines else "(no debate exchanges)",
        "integrated_rules": "\n".join(f"- {r}" for r in integrated_rules) if integrated_rules else "(none)",
        "justified_argument": justified_text,
        "justification_status": justification_status,
    }


def build_eval_input_no_schema(log: dict[str, Any]) -> dict[str, Any]:
    """スキーマなし版 (cli_no_schema.py) のログを、build_eval_input と同じ形に変換する.

    free-text の各発話を schema 版の評価入力フィールドに対応付け、同一の評価器・
    ルーブリック (evaluate_with_llm) で採点できるようにする。
    """
    dialogue: dict[str, Any] = log.get("dialogue", {}) or {}
    ag2_counter = dialogue.get("ag2_counter", "")
    ag1_counter = dialogue.get("ag1_counter", "")

    debate_lines: list[str] = []
    if ag2_counter:
        debate_lines.append(f"[counter] AG2 → AG1:\n  {ag2_counter}")
    if ag1_counter:
        debate_lines.append(f"[counter] AG1 → AG2:\n  {ag1_counter}")

    return {
        "mode": "no-schema",
        "method_context": NO_SCHEMA_METHOD_CONTEXT,
        "question": log.get("question") or "",
        "agent1_stance": log.get("agent1_stance") or "(not provided)",
        "agent2_stance": log.get("agent2_stance") or "(not provided)",
        "ag1_initial_opinion": dialogue.get("ag1_claim") or "(none)",
        "ag2_initial_opinion": dialogue.get("ag2_claim") or "(none)",
        "debate_history": "\n\n".join(debate_lines) if debate_lines else "(no debate exchanges)",
        "integrated_rules": dialogue.get("agreement_core") or "(none)",
        "justified_argument": dialogue.get("ag1_new_claim") or "(no conclusion)",
        "justification_status": "no-schema",
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

Both agents have fixed stances. Judge whether the dialogue produces a coherent, useful, and fair final position
from the information shown below. Use the method-specific context only to interpret the log format; do not reward
or penalize a run merely because it uses, or does not use, a formal schema.
""".strip()

SCHEMA_METHOD_CONTEXT = """
This run uses the proposed schema-based dialectical method, based on ASPIC+-style argumentation.

--- Argument Schema ---
Each argument is a sequence of rules. A rule has:
  - antecedent:
      - strong:         Established premises (must hold for the rule to fire)
      - weak_negation:  Defeasible assumptions (can be attacked by undercut)
  - consequent: The conclusion derived from the antecedent

Each argument exposes:
  - Conc: list of conclusions (consequents of the final rule)
  - Ass:  list of defeasible assumptions (weak_negation items across all rules)

--- Attack Types ---
  - rebut:    The attacker's Conc explicitly negates a Conc of the target argument.
              (direct clash of conclusions)
  - undercut: The attacker's Conc explicitly negates an Ass of the target argument.
              (attacks a defeasible assumption the target relies on)

--- Dialogue Flow ---
  1. Each agent (AG1, AG2) generates a main argument for their position.
  2. The opponent attempts to defeat it (rebut or undercut) → type "defeat"
  3. The proponent counters the defeat → type "counter"
  4. Defeat validity is checked; if cycles resolve, the thread closes.
  5. Warrants are extracted, generalized, and integrated into reusable rules.
  6. A new main argument is generated using the integrated rules.
  7. The argument that cannot be defeated is declared justified.
""".strip()

NO_SCHEMA_METHOD_CONTEXT = """
This run is the no-schema baseline.

--- Dialogue Format ---
The agents produce free-text claims and counters without formal Conc/Ass fields, attack validation, or an explicit
justification proof. The logged agreement core is a free-text synthesis of shared principles, and the final response
is AG1's revised claim after considering that agreement core.

--- Dialogue Flow ---
  1. AG1 gives an initial claim from its stance.
  2. AG2 counters AG1.
  3. AG2 gives an initial claim from its stance.
  4. AG1 counters AG2.
  5. A shared agreement core is generated.
  6. AG1 gives a revised final claim based on that agreement core.
""".strip()

SCORING_INSTRUCTION = """
Rate the above dialectical reasoning on a scale from 1 to 10 for each of the following:

1. Coherence      – Does the final synthesis follow logically from the initial opinion and counterarguments?
2. Originality    – Does the synthesis demonstrate novel insight, creative framing, or non-obvious conclusions?
3. Dialecticality – Does the response meaningfully integrate both perspectives, showing fair reasoning and synthesis?
4. Validity       – Are the method's own dialectical commitments sound when re-examined from each agent's stance?
                    For schema-based runs, check whether attacks, counters, status assignments, and justified/defensible
                    outcomes are warranted by the stated Conc/Ass and stances. For no-schema runs, check whether the
                    counters and final revised claim fairly answer the opposing stance and avoid unsupported concessions
                    or ignored objections. A high score means the debate closes or synthesizes for good reasons; a low
                    score means important stance-consistent objections were mishandled or overlooked.

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

AG1 Initial Position:
{response['ag1_initial_opinion']}

AG2 Initial Position:
{response['ag2_initial_opinion']}

Debate History:
{response['debate_history']}

Integrated Rules or Agreement Core:
{response['integrated_rules']}

Final Output:
{response['justified_argument']}
Justification status: {response['justification_status']}

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
