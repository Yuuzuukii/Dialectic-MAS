"""LLM 評価用の入力整形・効率指標・スコア集計・LLM 採点を行うヘルパ群."""

from __future__ import annotations

import json
from typing import Any


def _strip_period(text: str) -> str:
    """文末ピリオドを除いた文を返す（テンプレート連結時の二重ピリオド防止）."""
    t = text.strip()
    return t[:-1] if t.endswith(".") else t


def _strip_leading_connective(text: str) -> str:
    """文頭の接続語（Therefore, / Thus, / Hence,）を除く.

    モデルは consequent や一部 strong premise の文頭に "Therefore," を埋め込むことがある。
    描画側でも接続語を付けるため、そのままだと "So Therefore, ..." のように二重化する。
    """
    t = text.strip()
    low = t.lower()
    for connective in ("therefore,", "therefore ", "thus,", "thus ", "hence,", "hence "):
        if low.startswith(connective):
            return t[len(connective) :].strip()
    return t


def _schema_utterance(argument_body: dict[str, Any], turn: dict[str, Any]) -> str:
    """Render a Schema Argument faithfully as a readable rule-by-rule view.

    擬似的な一続きの散文へ直すと、接続詞・大小文字・句読点を描画側が補う過程で
    原文にない不自然さが入り、weak_negation と rule の対応も失われる。ここでは各 rule の
    strong / weak_negation / consequent をそのまま段階表示する。

    先行 rule の consequent が後続 rule の strong に再利用される場合だけ、同じ文を
    再掲せず `Uses: result from Step N` と示す。攻撃対象はこの関数で発話本文へ捏造せず、
    `_turn_label` の `declared target` として全形式に共通して表示する。
    """
    del turn  # 攻撃メタ情報は本文ではなくラベル側だけで表示する。
    rules = argument_body.get("rules") or []
    if not rules:
        return "(no argument)"

    def _norm(s: str) -> str:
        cleaned = _strip_leading_connective(_strip_period(str(s)))
        return cleaned.strip().lower()

    lines = ["Reasoning:"]
    prior_results: dict[str, int] = {}
    for index, rule in enumerate(rules, start=1):
        antecedent = rule.get("antecedent") or {}
        explicit_strongs: list[str] = []
        referenced_steps: list[int] = []
        for value in antecedent.get("strong") or []:
            text = str(value).strip()
            if not text:
                continue
            prior_step = prior_results.get(_norm(text))
            if prior_step is None:
                explicit_strongs.append(text)
            elif prior_step not in referenced_steps:
                referenced_steps.append(prior_step)
        assumptions = [
            str(value).strip()
            for value in antecedent.get("weak_negation") or []
            if str(value).strip()
        ]
        consequent = _strip_leading_connective(
            str(rule.get("consequent", "")).strip()
        )

        lines.append(f"Step {index}:")
        if referenced_steps:
            refs = ", ".join(f"Step {step}" for step in referenced_steps)
            lines.append(f"  Uses: result from {refs}")
        if explicit_strongs:
            lines.append("  Given:")
            lines.extend(f"  - {value}" for value in explicit_strongs)
        if assumptions:
            lines.append("  Defeasible assumptions:")
            lines.extend(f"  - {value}" for value in assumptions)
        if not referenced_steps and not explicit_strongs and not assumptions:
            lines.append("  Given: (no stated premise or assumption)")

        result_label = "Final conclusion" if index == len(rules) else "Supports"
        lines.append(f"  {result_label}: {consequent or '(no stated conclusion)'}")
        if consequent:
            prior_results[_norm(consequent)] = index

    return "\n".join(lines)


def _turn_label(index: int, turn: dict[str, Any], id_to_no: dict[str, int]) -> str:
    """1ターン分のラベル行（誰が・何に対しての発話か）を組み立てる.

    評価器はプロトコル用語を知らないので、rebut / undercut / main といった内部語彙は
    ラベルに出さず、平易な言葉（new argument / responding to [Turn X] /
    challenges its conclusion|premise）で議論の流れを説明する。

    - schema / no_schema: `target_statement` は攻撃側が宣言した対象としてラベルに表示する。
      実際に対象Argument内に存在するとは描画側で断定しない。
    - mad / free_debate: 先頭は opening、2ターン目以降は直前ターンへの応答として示す。
    """
    agent = turn.get("agent", "?")
    attack = turn.get("attack")
    if not attack:
        if turn.get("type") == "main":
            return f"[Turn {index}] {agent} (new argument)"
        if index > 1:
            return f"[Turn {index}] {agent} (responding to [Turn {index - 1}])"
        return f"[Turn {index}] {agent}:"

    target_id = turn.get("target_id")
    if isinstance(target_id, str) and target_id in id_to_no:
        ref = f"responding to [Turn {id_to_no[target_id]}]"
    else:
        ref = "responding to an earlier argument"

    target_statement = turn.get("target_statement")
    if target_statement:
        noun = (
            "conclusion"
            if turn.get("target_field") == "Conc"
            else "defeasible assumption"
        )
        quoted_target = json.dumps(str(target_statement).strip(), ensure_ascii=False)
        return (
            f"[Turn {index}] {agent} ({ref}; "
            f"declared target — {noun}: {quoted_target})"
        )
    return f"[Turn {index}] {agent} ({ref})"


def _format_turn_unified(turn: dict[str, Any], index: int, id_to_no: dict[str, int]) -> str:
    """1 ターン分をラベル行 + 発話本体の統一フォーマットへ整形する.

    schema: Argument JSON を発話体の英文へ機械的に変換（_schema_utterance）。
    no_schema / mad / free_debate: 原文をそのまま使い、ラベル行だけを揃える。
    """
    label = _turn_label(index, turn, id_to_no)
    argument = turn.get("argument")

    if isinstance(argument, dict):
        body = argument.get("Argument")
        if isinstance(body, dict) and "rules" in body:
            return f"{label}\n{_schema_utterance(body, turn)}"
        return f"{label}\n{json.dumps(argument, ensure_ascii=False, indent=2)}"

    if isinstance(argument, str) and argument.strip():
        return f"{label}\n{argument.strip()}"

    return f"{label}\n(no argument)"


def build_eval_input(
    log: dict[str, Any], *, include_integrated_rules: bool = True
) -> dict[str, Any]:
    """実行ログを、LLM 評価器へ渡す入力 dict に整形する.

    `include_integrated_rules=False` にすると、中立的なスレッド区切りは残すが、
    統合フェーズの生成物である統合ルールの文面は埋め込まない。
    統合ルールはターン単位の議論（main/defeat/counter）そのものではなく合成フェーズの
    出力なので、「議論部分だけ」を評価したい場合（例: 純粋な pairwise/flow の
    Constructiveness）に使う。

    ログは question / agent1_stance / agent2_stance / dialogue_history /
    final_answer / integrated_rules / metrics を持つ。schema / no_schema / free_debate /
    mad は argument の表現形式が異なるだけで、整形ロジックも評価プロンプトも共通。
    schema の JSON は発話体の自然文へ変換し、攻撃対象（どの結論/前提を狙ったか）を
    明示する。

    main ターンの status（justified/overruled/defensible）は評価者へ勝敗として見せない。
    次の main が実在するときだけ、中立的な境界
    `The preceding exchange has ended. A new argument follows.` を挿入する。
    末尾では、include_integrated_rules=True かつ実際に共有ルールがある場合だけその文面を示す。

    schema/no_schema は、1ラウンド（AG1 が proponent の main スレッド → AG2 が
    proponent の main スレッド、の2本）が両方とも justified に至らなかった場合、
    両者の warrant を汎化・統合した「integrated rule」を次ラウンドの土台にする
    （src/agent/nodes.py の generalize/integrate/add_integrated_rule）。この統合ルールの
    中身はこれまでログにも評価用 transcript にも出しておらず、最終回答だけがそれを
    参照して書かれるため、評価者（や人間の読み手）から見ると transcript のどこにも
    根拠がない結論に見えてしまっていた。ここではラウンドの区切り（2本目の main の
    決着）で、実際に使われた統合ルールの文面をそのまま transcript に挿入する。
    ラウンドは常に AG1 → AG2 の順（add_integrated_rule が次ラウンド開始時に
    current_proponent を AG1 にリセットする）なので、main レコードを1から数えて
    偶数番目（2本目・4本目…）の決着ごとに、未使用の integrated_rules を1つずつ
    順番に対応させればよい。
    """
    dialogue_history: list[dict[str, Any]] = log.get("dialogue_history") or []
    integrated_rules: list[str] = log.get("integrated_rules") or []

    id_to_no = {
        record["id"]: i
        for i, record in enumerate(dialogue_history, start=1)
        if isinstance(record.get("id"), str)
    }
    transcript_lines: list[str] = []
    pending_status: str | None = None
    main_count = 0
    rule_index = 0

    def _emit_transition_note(*, has_next_argument: bool) -> None:
        nonlocal rule_index
        has_shared_rule = (
            include_integrated_rules
            and pending_status in ("overruled", "defensible")
            and main_count % 2 == 0
            and rule_index < len(integrated_rules)
        )
        if has_next_argument:
            note = "— The preceding exchange has ended. A new argument follows."
            if not has_shared_rule:
                transcript_lines.append(note)
                return
            rule = integrated_rules[rule_index]
            rule_index += 1
            transcript_lines.append(
                f'{note} The new argument is based on this shared rule: "{rule}"'
            )
            return
        if has_shared_rule:
            rule = integrated_rules[rule_index]
            rule_index += 1
            transcript_lines.append(
                f'— Shared rule produced after the preceding exchanges: "{rule}"'
            )

    for i, record in enumerate(dialogue_history, start=1):
        if record.get("type") == "main" and pending_status is not None:
            _emit_transition_note(has_next_argument=True)
        transcript_lines.append(_format_turn_unified(record, i, id_to_no))
        if record.get("type") == "main":
            main_count += 1
            pending_status = record.get("status")
    if pending_status is not None:
        _emit_transition_note(has_next_argument=False)

    final_answer = log.get("final_answer")
    final_answer_text = (
        final_answer.strip()
        if isinstance(final_answer, str) and final_answer.strip()
        else "(no final answer)"
    )

    return {
        "question": log.get("question", ""),
        "agent1_stance": log.get("agent1_stance") or "(not provided)",
        "agent2_stance": log.get("agent2_stance") or "(not provided)",
        "debate_transcript": "\n\n".join(transcript_lines)
        if transcript_lines
        else "(no dialogue)",
        "final_answer": final_answer_text,
        # 統合ルール（両者が合意した warrant の蒸留）。constraint_preservation で
        # 「スタンスを取り込めているか」を採点する際の入力に使う（transcript とは別扱い）。
        "integrated_rules": integrated_rules,
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


SCORING_INSTRUCTION = """
You are an evaluator LLM. Your task is to rate the following dialectical reasoning output on a scale from 1 to 10 for each of the following.

For all four axes, judge the debate as a dialectical PROCESS, not just the final answer in isolation:
a well-run dialectical process is one where (i) each objection targets a specific claim or assumption
actually made by the other side, rather than a vague or generic rebuttal; (ii) the side being objected to
either concedes the point, refutes it with substantive new reasoning, or shows why it doesn't hold — it
does not ignore the objection or simply repeat its prior position unchanged; (iii) the positions narrow or
sharpen over the course of the transcript as specific objections are raised and answered, rather than both
sides restating their opening case in different words turn after turn; and (iv) the final answer's degree
of confidence matches how decisively the process actually resolved things — if one side's claims held up
against every objection raised, a confident conclusion in that side's favor is warranted; if neither side's
claims held up decisively, an answer that plainly says so (without overclaiming a winner) is equally valid.
The failure mode to penalize is a confident final answer that the transcript does not actually support, in
either direction — not the mere fact that the debate ended without a decisive winner.

1. Coherence      – Does the final synthesis follow, step by step, from the specific claims, objections, and responses that actually occurred in the transcript — so that a reader could trace which claim was made, which objection targeted it, how that objection was answered or conceded, and how the final answer follows from that specific chain — rather than following only loosely from the general topic, restating the initial positions, or asserting a conclusion the transcript does not actually trace a path to?
2. Originality    – Does the synthesis demonstrate novel insight, creative framing, or non-obvious conclusions, rather than simply restating one side's stance or a generic summary of both sides?
3. Dialecticality – Does each objection in the transcript engage with a specific claim or assumption actually made by the other side (rather than a generic or straw-man version of it), and does the responding side substantively address that specific point — conceding it, refuting it with new reasoning, or showing why it doesn't hold — rather than ignoring it or merely repeating a prior claim unchanged? A high-dialecticality debate shows genuine back-and-forth, with each side's position visibly shaped by what the other side actually said, rather than two monologues running in parallel.
4. Validity       – Are the debate's own reasoning commitments sound when re-examined from each agent's stance? Check whether each turn's objections and responses genuinely engage with the specific claim or assumption they are responding to, rather than talking past it or restating a prior position unchanged, and whether the final answer is fairly warranted by the transcript and both agents' stances — including whether its confidence level matches how decisively the process actually resolved, per the guidance above. A high score means the debate closes or synthesizes for good reasons; a low score means important stance-consistent objections were mishandled, ignored, or unsupported, or the final answer claims more certainty than the transcript earned.

Scoring rubric:
  9–10: Outstanding – excellent quality for the axis
  7–8:  Good – solid, with minor issues
  5–6:  Adequate – average quality, some issues
  1–4:  Weak – lacking clarity, logic, originality, validity, or synthesis

IMPORTANT: Rate strictly. Perfect scores are rare.

Evaluate the following debate:

Question:
{question}

AG1 Stance:
{agent1_stance}

AG2 Stance:
{agent2_stance}

Debate Transcript (chronological, each turn is one agent's argument):
{debate_transcript}

Final Answer:
{final_answer}

Respond ONLY with a JSON object:
{{
  "coherence": <int>,
  "originality": <int>,
  "dialecticality": <int>,
  "validity": <int>,
  "evaluator_model": "<model name>"
}}
""".strip()


def evaluate_with_llm(response: dict[str, Any], evaluator_model: Any) -> dict[str, Any]:
    """Evaluate a Dialect-MAS run using an LLM as evaluator.

    `response` should be the output of build_eval_input().
    `evaluator_model` must expose .model (str) and .invoke(prompt: str) -> str.
    Returns a dict with numeric scores and model info.
    """
    prompt = SCORING_INSTRUCTION.format(**response)

    try:
        raw: str = evaluator_model.invoke(prompt)
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
