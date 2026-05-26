from __future__ import annotations

import json
from typing import Any


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
        return json.loads(text)
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
        "question": question,
        "ag1_initial_opinion": "\n".join(ag1_mains) if ag1_mains else "(none)",
        "ag2_initial_opinion": "\n".join(ag2_mains) if ag2_mains else "(none)",
        "debate_history": "\n\n".join(debate_lines) if debate_lines else "(no debate exchanges)",
        "integrated_rules": "\n".join(f"- {r}" for r in integrated_rules) if integrated_rules else "(none)",
        "justified_argument": justified_text,
        "justification_status": justification_status,
    }


FRAMEWORK_CONTEXT = """
You are evaluating a multi-agent dialectical argumentation system based on ASPIC+.

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

SCORING_INSTRUCTION = """
Rate the above dialectical reasoning on a scale from 1 to 10 for each axis:

1. Coherence  – Does the justified argument follow logically from the debate and integrated rules?
2. Originality – Does the final argument show novel insight beyond simply restating initial positions?

Scoring rubric:
  9–10: Outstanding   7–8: Good   5–6: Adequate   1–4: Weak

IMPORTANT: Rate strictly. Perfect scores are rare.

Respond ONLY with a JSON object:
{
  "coherence": <int>,
  "originality": <int>,
  "evaluator_model": "<model name>"
}
""".strip()


def evaluate_with_llm(response: dict[str, Any], evaluator_model: Any) -> dict[str, Any]:
    """
    Evaluate a Dialect-MAS run using an LLM as evaluator.
    `response` should be the output of build_eval_input().
    `evaluator_model` must expose .model (str) and .invoke(prompt: str) -> str.
    Returns a dict with numeric scores and model info.
    """
    prompt = f"""
{FRAMEWORK_CONTEXT}

--- Debate to Evaluate ---

Question:
{response['question']}

AG1 Initial Opinion (Conc):
{response['ag1_initial_opinion']}

AG2 Initial Opinion (Conc):
{response['ag2_initial_opinion']}

Debate History (type / agent / attack / conclusion):
{response['debate_history']}

Integrated Rules (derived from debate):
{response['integrated_rules']}

Final Justified Argument (Conc):
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
        print(f"Evaluation failed: {e}")
        return {
            "coherence": None,
            "originality": None,
            "evaluator_model": getattr(evaluator_model, "model", "unknown"),
        }
