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
    """スキーマの Argument (rules/Conc/Ass) をエージェントの発話体の英文へ変換する.

    複数 rule がある場合は中間 consequent も推論ステップとして残し、rule 連鎖を
    そのまま辿れるようにする。旧実装は全 rule の strong をまとめて末尾 consequent だけを
    結論にしており、「どの前提からどう推論したか」という schema の構造的な強みが
    評価者から見えず、平坦な前提列＝generic な反論に見えて建設性で不当に減点されていた。

    - 各 rule を `{grounds}. {So|Therefore,} {consequent}.` の推論ステップとして描画
      （中間 rule は "So"、最終 rule は "Therefore,"）。
    - weak_negation（未検証の前提）は末尾に付記。
    - 攻撃ターン（attack/target_statement あり）は冒頭に反論の対象を明示:
      `I have a counter argument against the {opinion|premise} "{target_statement}".`
    """
    rules = argument_body.get("rules") or []
    parts: list[str] = []
    if turn.get("attack") and turn.get("target_statement"):
        noun = "opinion" if turn.get("target_field") == "Conc" else "premise"
        parts.append(
            f"I have a counter argument against the {noun} "
            f'"{_strip_period(str(turn["target_statement"]))}".'
        )

    # chain 構造では非末尾 consequent が次 rule の strong 前提に再出現する。そのまま
    # rule 単位で描画すると同じ結論文が二重に出るため、consequent と一致する strong は
    # 「連鎖のつなぎ」とみなして描画から省く（推論の流れは connector で表現される）。
    def _norm(s: str) -> str:
        return _strip_period(str(s)).strip().lower()

    consequent_norms = {
        _norm(rule.get("consequent", "")) for rule in rules if rule.get("consequent")
    }

    assumptions: list[str] = []
    n = len(rules)
    for i, rule in enumerate(rules):
        antecedent = rule.get("antecedent") or {}
        strongs = [
            _strip_leading_connective(_strip_period(s))
            for s in antecedent.get("strong") or []
            if s and s.strip() and _norm(s) not in consequent_norms
        ]
        assumptions += [
            _strip_period(a)
            for a in antecedent.get("weak_negation") or []
            if a and a.strip()
        ]
        consequent = _strip_leading_connective(_strip_period(str(rule.get("consequent", ""))))
        grounds = ". ".join(strongs)
        connector = "Therefore," if i == n - 1 else "So"
        if grounds and consequent:
            parts.append(f"{grounds}. {connector} {consequent}.")
        elif consequent:
            parts.append(f"{connector} {consequent}.")
        elif grounds:
            parts.append(f"{grounds}.")

    if assumptions:
        joined = "; ".join(assumptions)
        parts.append(f"(This relies on the assumption that {joined}.)")
    return " ".join(parts) if parts else "(no argument)"


def _turn_label(index: int, turn: dict[str, Any], id_to_no: dict[str, int]) -> str:
    """1ターン分のラベル行（誰が・何に対しての発話か）を組み立てる.

    - schema（発話体変換される）: 対象の中身は発話本体に出るので、ラベルは
      `(attack — responds to [Turn X])` の軽い参照のみ。
    - no_schema（原文のまま）: 発話本体に対象が出ないので、ラベル側に
      攻撃対象（結論/前提とその文）を明示する。
    - attack メタ情報が無いターン（mad/free_debate/main）: 種別のみ。
    """
    agent = turn.get("agent", "?")
    attack = turn.get("attack")
    if not attack:
        if turn.get("type") == "main":
            return f"[Turn {index}] {agent} (main argument)"
        return f"[Turn {index}] {agent}:"

    ref = ""
    target_id = turn.get("target_id")
    if isinstance(target_id, str) and target_id in id_to_no:
        ref = f" — responds to [Turn {id_to_no[target_id]}]"

    argument = turn.get("argument")
    is_schema = isinstance(argument, dict)
    if is_schema:
        return f"[Turn {index}] {agent} ({attack}{ref})"

    target_statement = turn.get("target_statement")
    if target_statement:
        noun = "opinion" if turn.get("target_field") == "Conc" else "premise"
        return (
            f"[Turn {index}] {agent} ({attack}{ref} — "
            f'attacks the {noun} "{_strip_period(str(target_statement))}")'
        )
    return f"[Turn {index}] {agent} ({attack}{ref})"


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


_THREAD_TRANSITION_NOTE = {
    "justified": "The argument above withstood every objection raised against it.",
    "overruled": (
        "The argument above could not be defended against the objections raised, "
        "so a new argument is introduced below."
    ),
    "defensible": (
        "Neither side could conclusively resolve the argument above within the "
        "attempt limit, so a new argument is introduced below."
    ),
}


def build_eval_input(
    log: dict[str, Any], *, include_integrated_rules: bool = True
) -> dict[str, Any]:
    """実行ログを、LLM 評価器へ渡す入力 dict に整形する.

    `include_integrated_rules=False` にすると、スレッド区切りの説明文（ト書き）は
    そのまま挿入するが、統合フェーズの生成物である統合ルールの文面は埋め込まない。
    統合ルールはターン単位の議論（main/defeat/counter）そのものではなく合成フェーズの
    出力なので、「議論部分だけ」を評価したい場合（例: 純粋な pairwise/flow の
    Constructiveness）に使う。

    ログは question / agent1_stance / agent2_stance / dialogue_history /
    final_answer / integrated_rules / metrics を持つ。schema / no_schema / free_debate /
    mad は argument の表現形式が異なるだけで、整形ロジックも評価プロンプトも共通。
    schema の JSON は発話体の自然文へ変換し、攻撃対象（どの結論/前提を狙ったか）を
    明示する。

    main ターンの status（justified/overruled/defensible）は、プロトコル用語を使わない
    1行のト書きとして、そのスレッドの最後（＝次の main の直前、または末尾）に挿入する
    （例: 「上の議論は反論に耐えられなかったため、新しい議論が下に続く」）。手法固有の
    語彙は使わず、採点基準（SCORING_INSTRUCTION）自体は変更しない。

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

    def _emit_transition_note() -> None:
        nonlocal rule_index
        note = _THREAD_TRANSITION_NOTE.get(pending_status or "")
        if not note:
            return
        if (
            include_integrated_rules
            and pending_status in ("overruled", "defensible")
            and main_count % 2 == 0
            and rule_index < len(integrated_rules)
        ):
            rule = integrated_rules[rule_index]
            rule_index += 1
            transcript_lines.append(
                f"— {note} Both sides' reasoning so far was distilled into a shared "
                f'rule that the next argument is built on: "{rule}"'
            )
        else:
            transcript_lines.append(f"— {note}")

    for i, record in enumerate(dialogue_history, start=1):
        if record.get("type") == "main" and pending_status is not None:
            _emit_transition_note()
        transcript_lines.append(_format_turn_unified(record, i, id_to_no))
        if record.get("type") == "main":
            main_count += 1
            pending_status = record.get("status")
    if pending_status is not None:
        _emit_transition_note()

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
