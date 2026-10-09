"""議論システムの全プロンプト定義（SYSTEM テンプレート・共有ブロック・補助ビルダ）."""

# プロンプトは「SYSTEM（役割・論証の文法・タスク定義・出力契約）」と
# 「USER（その手番でしか意味を持たない可変入力）」に分離して管理する。
#
# 設計指針（CLAUDE.md / GPT-5 Prompting Guide）:
# - 指示は XML 風タグでセクション化し、追従性を上げる。
# - 共通ルール（論証の文法・攻撃の定義・stance grounding）は下記の共有ブロックに集約し、
#   テンプレート間の重複＝矛盾混入を避ける。
# - with_structured_output のスキーマ（schema/llm_outputs.py）と自然言語指示を矛盾させない。
#   連鎖規則の詳細は ArgumentBody スキーマ側が担保するため、ここでは要点のみ記す。
# - SYSTEM/USER の合成・指示文の組み立て（補助ビルダ）も本ファイルに集約し、
#   実際のメッセージ列の組み立て（呼び出し側）は arguments.py が行う。

from __future__ import annotations

from typing import Any

from .schema.types import AgentName
from .target_selection import options_block

# ---- 共有ブロック（複数テンプレートで再利用） ----

# grounding は全トピック共通の単一ルール（トピック種別によるモード分離はしない）。
# 2行目の「スタンス優先原則」により、スタンスが全論点を settle している正当性検証
# シナリオ（camera/curry）では事実上厳密に、スタンスが支持材料について沈黙している
# 一般トピックでは幅広い一般知識の利用を許す形で、単一の文言のまま両立させる。
_GROUNDING = """\
<grounding>
- Your values, priorities, and the position you argue for come from your stance; never contradict your stance or adopt priorities it does not contain.
- Where your stance, the target argument, the dialogue history, or the integrated rules already provide the facts or rules that settle a point, argue from those; do not override or replace them with outside knowledge.
- Where they are silent, you may draw on general knowledge — facts, examples, analogies, mechanisms — to support your position or to challenge the other side's reasoning.
</grounding>"""

# "premises"/"assumptions"/"conclusion" のような名詞は、no_schema の出力にそのまま
# 見出しラベル（"Premise 1:", "Conclusion:"）として echo されることが実測で確認された
# ため、ラベル化されにくい言い回しを使う（要求内容は変えていない）。
_ARGUMENTATION_RULES = """\
<argumentation_rules>
- Make clear what you are relying on to support your position.
- Your final position must follow directly from what you have stated, with no implicit logical leap.
- Your final position must clearly express your opinion on the Issue in a specific way.
- Include the specific facts, distinctions, and reasoning your position actually depends on; do not pad with repetition or restate the same point in different words.
</argumentation_rules>"""

_SCHEMA_OVERLAY = """\
<schema_overlay>
Represent Argument as a structured object consisting of rules, Conc, and Ass.
- rules is a finite sequence of rules r_1, ..., r_n.
- Each rule has an antecedent and a consequent.
- Antecedents may contain strong premises and weak_negation assumptions (strong and weak literals in Prakken & Sartor's terms).
- A strong premise is the consequent of an EARLIER rule in this Argument, and nothing else. A rule names its strong premises by the numbers of the earlier rules it relies on (from_rules); each premise is then that rule's consequent. A rule that cites no earlier rule has no strong premise. Your stance, the dialogue history, and general knowledge cannot be cited as premises: a claim you take from them must first be stated as the consequent of a rule of its own. Strong premises are not assumptions: never list them in Ass.
- A weak_negation entry is an exception clause ("unless X", "as long as there is no evidence that X"): the rule applies by default and stops applying only if X is shown to hold; it needs no support of its own. Write it as the presumption "X is not the case" (e.g. "no evidence that Y fails here", "Z does not occur in this case"). It must be a specific claim that could in principle be proven false by evidence that X actually holds — an attacker undercuts the Argument by proving X. Use weak_negation wherever your reasoning genuinely rests on the absence of something that would block it (an exception you presume absent, a risk you presume not to occur, an obstacle you presume is not present): when a step of your reasoning holds only as long as nothing blocks it, state that as "X is not the case" rather than silently treating it as given. A weak_negation entry is always a negation; never write a positive assumption ("X is the case") there — a positive claim is not an exception clause: state it as the consequent of a rule. Do not put scope stipulations, definitions, or framing choices ("we are evaluating only Y") in weak_negation — those are not defeasible assumptions and cannot be coherently undercut; state them as the consequent of a rule or fold them into the reasoning directly instead.
- The FIRST rule has no strong premise (from_rules is empty): its consequent is one claim that you hold, taken from your stance (or, where your stance is silent, from the dialogue or general knowledge). It may carry weak_negation entries. A later rule may also have no strong premise, but only to state another claim that you hold in the same way; whenever a later rule cites premises, it cites only earlier rules.
- Conc contains the conclusions derived by the rules.
- Ass contains the weak_negation assumptions used by the rules.
- Every consequent except the final one must be cited by a later rule: the final rule is the warrant of the Argument, and the rules before it lead to it.
- Use as many rules as your reasoning genuinely needs and no more: add a rule whenever it introduces a materially new fact, point, or inferential step that strengthens your case; do not add a rule that merely restates an earlier one.
- Each rule's consequent must state a materially new claim — a new fact, a new point, or a new inferential step — not a paraphrase or near-synonym of an earlier rule's consequent (e.g. "the attack is insufficient" -> "the attack fails to show invalidity" -> "the attack does not defeat the conclusion" is the same claim restated three times, not three rules). If a later rule's consequent would just restate an earlier one in different words, merge them into a single rule instead.
- When attacking (defeat/counter), the conclusions of your Argument (the consequents of its rules) must include the contradiction of the target item you choose in Attack: for a rebut, the contradictory of one of the target's conclusions; for an undercut, the contradictory of one of the target's assumptions. Build it from the claims you hold, through your chain of rules.
- Do not satisfy this by appending a short final rule that merely quotes or paraphrases the target ("The target says X, but Y") while your earlier rules argue a generic, self-contained point that never touches the target. The contradiction of the chosen target item must be what your chain of rules actually establishes.
</schema_overlay>"""

_ATTACK_TYPES = """\
<attack_types>
- rebut: a conclusion of the attacker explicitly negates a conclusion (Conc) of the target.
- undercut: a conclusion of the attacker explicitly negates an assumption (Ass) of the target.
</attack_types>"""

_PROTOCOL_FLOW = """\
<protocol_flow>
You and the other agent (AG1 and AG2) debate one Issue, each from a fixed stance, over one or more rounds.
A round proceeds as a dialectical thread:
- A proponent states a main argument (phase "main").
- The opponent attacks it with a defeating argument (phase "defeat", via rebut or undercut).
- The proponent defends with a counterargument (phase "counter"). A rebut can be blocked by an undercut.
- The thread closes with one outcome, recorded on the main argument's "status":
    - justified  – the main survives every attack → the debate ends with this answer.
    - overruled  – the main is defeated and cannot be defended.
    - defensible – the two sides defeat each other; the conflict stays unresolved.
When neither side's main is justified, the shared warrants are generalized and merged into reusable
"integrated rules" that BOTH sides accept. In the NEXT round the proponent must build a NEW main argument
grounded in those integrated rules, different from every earlier main and not vulnerable to the same attacks.
The debate ends when a main is justified, or when the round limit is reached (then the final answer is
produced from the debate so far and the integrated rules).
</protocol_flow>"""

_HISTORY_FORMAT = """\
<history_format>
Prior turns of this debate are provided as preceding messages. Each message's content is a JSON object:
  {"id", "round", "phase", "agent", ["status"], ["attack","target_id","target_statement"], "Argument": {"rules","Conc","Ass"}}
- "phase" is one of main / defeat / counter. "status" (justified/overruled/defensible) appears only on a
  main turn, once its thread has closed; a defeat/counter turn carries no outcome field of its own.
- "attack"/"target_id"/"target_statement" (on defeat/counter) show exactly what was attacked.
- In each rule, "strong" lists the premises, which are the consequents of the earlier rules named in "from_rules".
- A message whose "agent"/name equals YOUR identity is your own past turn; the other agent's are your opponent's.
Use this history to stay consistent with the current round and integrated rules.
</history_format>"""

# 最終回答（generate_final_answer）専用の history_format。ARGUMENT_SYSTEM 用の
# _HISTORY_FORMAT は読者が AG1/AG2 本人であることを前提にした一人称の文言
# （"YOUR identity" 等）だが、最終回答は AG1/AG2 どちらの stance も代弁しない
# 中立な統合役として書くため、三人称の文言に言い換える。
_FINAL_ANSWER_HISTORY_FORMAT = """\
<history_format>
The dialogue history below is a JSON array of turns. Each turn is an object:
  {"id", "round", "phase", "agent", ["status"], ["attack","target_id","target_statement"], "Argument": {"rules","Conc","Ass"}}
- "agent" is which side (AG1 or AG2) produced that turn.
- "phase" is one of main / defeat / counter. "status" (justified/overruled/defensible) appears only on a
  main turn, once its thread has closed; a defeat/counter turn carries no outcome field of its own.
- "attack"/"target_id"/"target_statement" (on defeat/counter) show exactly what was attacked.
- Each "Argument" is a chain of rules: each rule's "consequent" follows from its antecedent's "strong" (and,
  if present, "weak_negation") premises, and one rule's consequent may feed the next rule's premises. "Conc"
  lists the chain's conclusions; "Ass" lists its weak_negation assumptions.
</history_format>"""

_FINAL_ANSWER_HISTORY_FORMAT_FREE = """\
<history_format>
The dialogue history below is a JSON array of turns. Each turn is an object:
  {"id", "round", "phase", "agent", ["status"], ["attack","target_id","target_statement"], "Argument": "<free-text argument>"}
- "agent" is which side (AG1 or AG2) produced that turn.
- "phase" is one of main / defeat / counter. "status" (justified/overruled/defensible) appears only on a
  main turn, once its thread has closed; a defeat/counter turn carries no outcome field of its own.
- "attack"/"target_id"/"target_statement" (on defeat/counter) show exactly what was attacked.
</history_format>"""

_HISTORY_FORMAT_FREE = """\
<history_format>
Prior turns of this debate are provided as preceding messages. Each message's content is a JSON object:
  {"id", "round", "phase", "agent", ["status"], ["attack","target_id","target_statement"], "Argument": "<free-text argument>"}
- "phase" is one of main / defeat / counter. "status" (justified/overruled/defensible) appears only on a
  main turn, once its thread has closed; a defeat/counter turn carries no outcome field of its own.
- "attack"/"target_id"/"target_statement" (on defeat/counter) show exactly what was attacked.
- A message whose "agent"/name equals YOUR identity is your own past turn; the other agent's are your opponent's.
Use this history to stay consistent with the current round and integrated rules.
</history_format>"""


def _system(*blocks: str) -> str:
    """XML タグ付きブロックを空行区切りで連結して 1 つの system プロンプトにする."""
    return "\n\n".join(block.strip() for block in blocks if block and block.strip())


class PromptTemplates:
    """各ノードが参照する SYSTEM プロンプト文字列の名前空間."""

    # ---- System: shared argument-construction framework ----
    ARGUMENT_SYSTEM_NO_SCHEMA = _system(
        _GROUNDING,
        _PROTOCOL_FLOW,
        _ARGUMENTATION_RULES,
        _HISTORY_FORMAT_FREE,
    )

    ARGUMENT_SYSTEM = _system(
        _GROUNDING,
        _PROTOCOL_FLOW,
        _ARGUMENTATION_RULES,
        _ATTACK_TYPES,
        _SCHEMA_OVERLAY,
        _HISTORY_FORMAT,
    )

    # Backward-compatible names. The phase-specific task now lives in HumanMessage.
    MAIN_ARGUMENT_SYSTEM = ARGUMENT_SYSTEM
    MAIN_ARGUMENT_SYSTEM_NO_SCHEMA = ARGUMENT_SYSTEM_NO_SCHEMA
    DEFEATING_ARGUMENT_SYSTEM = ARGUMENT_SYSTEM
    DEFEATING_ARGUMENT_SYSTEM_NO_SCHEMA = ARGUMENT_SYSTEM_NO_SCHEMA
    COUNTER_ARGUMENT_SYSTEM = ARGUMENT_SYSTEM
    COUNTER_ARGUMENT_SYSTEM_NO_SCHEMA = ARGUMENT_SYSTEM_NO_SCHEMA
    UNDERCUT_SYSTEM = ARGUMENT_SYSTEM
    UNDERCUT_SYSTEM_NO_SCHEMA = ARGUMENT_SYSTEM_NO_SCHEMA

    # 汎化(generalize)と統合(integrate)は別々の往復にせず、1回のLLM呼び出しで
    # 「両者のwarrantを汎化した上で1つの再利用可能ルールにまとめる」ところまで行う。
    _INTEGRATION_SYSTEM_BASE = _system(
        "<role>\n"
        "You are AG1 in this debate.\n"
        "You now act as the synthesis operator for the debate.\n"
        "Your task is to generalize each side's warrant into a reusable condition-to-conclusion "
        "criterion, then integrate both sides' criteria into one reusable rule for the next round.\n"
        "</role>",
        "<stance>\n{stance}\n</stance>",
        "<integration_principles>\n"
        "- Priority: preserving every distinct substantive requirement from both source stances "
        "outranks abstraction. Abstract the STRUCTURE of each side's warrant (the general "
        "condition-to-conclusion pattern, so the rule is usable by either side in the next round; "
        "do not merely list the warrants) — but never abstract away a specific named entity, legal "
        "or factual characterization, threshold, or affected group that is the substance of a "
        "requirement itself (e.g. keep 'protects an individual right', not just 'affects a right').\n"
        "- Use the source stances as a coverage check: the rule must not silently drop a distinct "
        "substantive requirement from either side, even one a compressed warrant did not repeat, "
        "and even if keeping it means the rule is less general than it could otherwise be.\n"
        "- When the sides support different outcomes, express one decision rule that says which "
        "outcome follows under each condition; do not combine opposing conditions under one OR "
        "and leave their outcomes ambiguous.\n"
        "- If opposing conditions can both be true, adjudicate them symmetrically using the same "
        "evidential threshold for both sides (magnitude, likelihood, reversibility, mitigation); "
        "do not give either side an automatic veto. Do not invent a precautionary presumption, "
        "burden shift, or tie-breaker absent from the warrants; if they do not determine the "
        "balance, preserve that as unresolved.\n"
        "- Do not discard AG2's warrant merely because it conflicts with AG1's stance, and do not "
        "simply restate AG1's own warrant as the result.\n"
        "- Do not choose a winner between the two sides, and do not produce a final answer to the "
        "original Issue.\n"
        "</integration_principles>",
    )

    INTEGRATION_SYSTEM_NO_SCHEMA = _INTEGRATION_SYSTEM_BASE

    INTEGRATION_SYSTEM = _system(
        _INTEGRATION_SYSTEM_BASE,
        "<schema_overlay>\n"
        "Represent the result as one structured rule:\n"
        "- consequent: the shared decision principle or outcome mapping.\n"
        "- rule: a single reusable rule preserving each side's condition-to-outcome mapping. "
        "Use OR only for conditions that support the same outcome.\n"
        "</schema_overlay>",
    )

    _FINAL_ANSWER_PRESERVATION = _system(
        "<constraint_preservation>\n"
        "- Before drafting, silently identify every distinct substantive constraint, requirement, "
        "condition, and consideration stated in AG1 Stance and AG2 Stance.\n"
        "- Account for every identified item in the answer: explicitly satisfy it, qualify it, "
        "or explain why it is overridden by another consideration.\n"
        "- Choosing one side's conclusion does not permit silently omitting the other side's "
        "requirements.\n"
        "- The dialogue, justified argument, and integrated rules may develop or resolve the "
        "stances, but they do not replace them. Restore any stance requirement that those "
        "intermediate representations omitted.\n"
        "- Preserve specific thresholds, exceptions, preconditions, affected groups, and named "
        "tradeoffs when they are material. Do not replace them with a generic 'both sides' summary.\n"
        "</constraint_preservation>",
        "<answer_style>\n"
        "- Lead with a direct answer, then give only the rationale needed to show how the material "
        "requirements from both stances were handled.\n"
        "- Never output the labels 'AG1' or 'AG2'. Refer to the substantive benefit, risk, or "
        "requirement instead of referring to a side or agent.\n"
        "- Do not mention agents, turns, rounds, the debate process, or internal protocol terms.\n"
        "- Apply any integrated rule silently in ordinary prose; do not quote it or describe it "
        "as an 'integrated rule', 'decision rule', or internal evaluation procedure.\n"
        "- Do not offer additional work or end with phrases such as 'If you want'.\n"
        "- Avoid repeating the same conclusion or caveat in multiple sections.\n"
        "</answer_style>",
    )

    # justified側: AG1が常に客観的な統合役として最終回答を書く（justifiedされたのが
    # AG1/AG2どちらのstanceでも、勝った側の代弁者ではなく中立な報告者として書く）。
    # schema/no_schema で dialogue_history 内の Argument の形式が違うため、
    # 対応する history_format（三人称版）を分けて埋め込む。
    FINAL_ANSWER_SYSTEM = _system(
        "<task>\n"
        "Based on the debate so far and the argument that was justified, write the final "
        "answer to the original question.\n"
        "</task>",
        _FINAL_ANSWER_HISTORY_FORMAT,
        _FINAL_ANSWER_PRESERVATION,
    )

    FINAL_ANSWER_SYSTEM_NO_SCHEMA = _system(
        "<task>\n"
        "Based on the debate so far and the argument that was justified, write the final "
        "answer to the original question.\n"
        "</task>",
        _FINAL_ANSWER_HISTORY_FORMAT_FREE,
        _FINAL_ANSWER_PRESERVATION,
    )

    # 合意（justified な決着）に至らないままラウンド上限に達したときの最終回答。
    # こちらも同様にAG1が客観的な統合役として書く。
    #
    # 弁証法議論はあくまで内部の推論過程であり、ユーザーに見えるのはこの最終回答のみ。
    # 「provisional / no consensus / 合意に至らなかった」等のプロトコル内部の経緯を
    # 回答に漏らすとユーザーを困惑させるため、内部経緯には言及させず、議論から最も
    # 支持される回答を1つ選んで通常の回答として書かせる。
    FINAL_ANSWER_NO_CONSENSUS_SYSTEM = _system(
        "<task>\n"
        "Based on the debate so far, write the final answer to the original question. "
        "Weigh the strengths of both sides' reasoning and commit to the best-supported "
        "answer, stating it directly with its supporting rationale. If integrated rules "
        "are provided below, ground your answer in them.\n"
        "</task>",
        "<calibration>\n"
        "Match your confidence to how decisively the debate actually resolved the question. "
        "If the strongest objections against your answer were substantively answered, state "
        "your conclusion with full confidence. If a serious objection was never adequately "
        "answered, say so as part of the answer itself — name the specific unresolved point "
        "and explain why you still lean one way despite it — rather than presenting the "
        "conclusion as more settled than the reasoning actually supports. Do not manufacture "
        "false certainty just to sound decisive.\n"
        "</calibration>",
        "<style>\n"
        "The debate above is internal reasoning; the reader sees only your answer. "
        "Do not mention the debate process, the agents, rounds, or whether agreement "
        "was reached. Write the answer as a direct, self-contained response to the "
        "question.\n"
        "</style>",
        _FINAL_ANSWER_HISTORY_FORMAT,
        _FINAL_ANSWER_PRESERVATION,
    )

    FINAL_ANSWER_NO_CONSENSUS_SYSTEM_NO_SCHEMA = _system(
        "<task>\n"
        "Based on the debate so far, write the final answer to the original question. "
        "Weigh the strengths of both sides' reasoning and commit to the best-supported "
        "answer, stating it directly with its supporting rationale. If integrated rules "
        "are provided below, ground your answer in them.\n"
        "</task>",
        "<calibration>\n"
        "Match your confidence to how decisively the debate actually resolved the question. "
        "If the strongest objections against your answer were substantively answered, state "
        "your conclusion with full confidence. If a serious objection was never adequately "
        "answered, say so as part of the answer itself — name the specific unresolved point "
        "and explain why you still lean one way despite it — rather than presenting the "
        "conclusion as more settled than the reasoning actually supports. Do not manufacture "
        "false certainty just to sound decisive.\n"
        "</calibration>",
        "<style>\n"
        "The debate above is internal reasoning; the reader sees only your answer. "
        "Do not mention the debate process, the agents, rounds, or whether agreement "
        "was reached. Write the answer as a direct, self-contained response to the "
        "question.\n"
        "</style>",
        _FINAL_ANSWER_HISTORY_FORMAT_FREE,
        _FINAL_ANSWER_PRESERVATION,
    )

    # ---- User: per-turn variable input ----
    FINAL_ANSWER_USER = """
Question: {question}

AG1 Stance: {agent1_stance}
AG2 Stance: {agent2_stance}
{integrated_rules_block}

Dialogue history:
{dialogue_history}

The argument that was justified:
{justified_argument}

Final check before returning:
- Do not output "AG1", "AG2", "integrated rule", or "decision rule".
- Ensure every material item from both stances is explicitly handled.
"""

    FINAL_ANSWER_NO_CONSENSUS_USER = """
Question: {question}

AG1 Stance: {agent1_stance}
AG2 Stance: {agent2_stance}
{integrated_rules_block}
Dialogue history:
{dialogue_history}

Most developed argument from the debate:
{justified_argument}

Final check before returning:
- Do not output "AG1", "AG2", "integrated rule", or "decision rule".
- Ensure every material item from both stances is explicitly handled.
"""

    # ---- Free debate (弁証法プロトコルを使わない自由討議ベースライン) ----
    # rebut/undercut/justified 等の概念を持ち込まない、自由記述の主張のみ。
    # 原論文(Du et al.)に倣い、簡潔さ・構造化禁止といった独自の style 指示は付与しない。
    # ラウンド上限到達後の統合・最終回答生成は、schema/no_schemaと共通の
    # INTEGRATION_SYSTEM* / FINAL_ANSWER_NO_CONSENSUS_SYSTEM を使う（free_debate.py 参照）。
    FREE_DEBATE_TURN_SYSTEM = _system(_GROUNDING)

    MAD_TURN_SYSTEM = _system(_GROUNDING)

    # 純粋なMAD（use_synthesis=False）でのみ使う、勝者を決めるjudge。use_synthesis=True の
    # 場合は代わりに schema/no_schemaと共通の INTEGRATION_SYSTEM* / FINAL_ANSWER_NO_CONSENSUS_SYSTEM
    # を使う（mad.py 参照）。
    MAD_JUDGE_SYSTEM = _system(
        "<role>\nYou are an independent judge. You did not participate in this debate.\n</role>",
        "<task>\nBased on the debate so far, select a single winner and formulate the final answer based on his opinion. however, there is no need to announce the winner within the text of the answer itself.\n</task>",
    )

    MAD_JUDGE_USER = """
Question: {question}

Dialogue history:
{dialogue_history}
"""


# ---- 補助ビルダ（SYSTEM 合成・手番ごとの指示文） ----
# 役割: ここでは「何を伝えるか（テキスト）」だけを組み立てる。
#       実際のメッセージ列（System + 履歴 + Human）の組み立ては arguments.py が行う。

# defeat フェーズ用 SYSTEM と counter フェーズ用 SYSTEM の対応表。
ATTACK_SYSTEM = {
    "defeat": PromptTemplates.DEFEATING_ARGUMENT_SYSTEM,
    "counter": PromptTemplates.COUNTER_ARGUMENT_SYSTEM,
}

ATTACK_SYSTEM_NO_SCHEMA = {
    "defeat": PromptTemplates.DEFEATING_ARGUMENT_SYSTEM_NO_SCHEMA,
    "counter": PromptTemplates.COUNTER_ARGUMENT_SYSTEM_NO_SCHEMA,
}


def compose_system(stance: str, task_system: str) -> str:
    """エージェントのスタンス（役割）とタスク定義を 1 つの system プロンプトに結合する."""
    return _system(stance, task_system)


def agent_system(stance: str, agent: AgentName, task_system: str) -> str:
    """エージェント identity + stance + タスク定義を 1 つの system プロンプトにする."""
    identity = (
        "<identity>\n"
        f'You are {agent} in this debate. In the message history, turns whose agent/name is "{agent}" '
        "are your own past turns; the other agent is your opponent.\n"
        "</identity>"
    )
    return _system(identity, compose_system(stance, task_system))


def synthesis_system(agent: AgentName, stance: str, task_system: str) -> str:
    """統合フェーズ用の AG1 synthesis system を組み立てる."""
    return task_system.format(agent=agent, stance=stance)


def main_instruction(state: Any) -> str:
    """主張生成の手番に渡す指示文（Issue + 改訂コンテキストなら統合ルール）を組む."""
    issue = state.question
    rules = getattr(state, "integrated_rules", []) or []
    debate_round = getattr(state, "debate_round", 1)
    lines = [
        "<task>",
        f"Round {debate_round}. Construct your main argument for the Issue.",
        "</task>",
        "",
        "<issue>",
        issue,
        "</issue>",
        "",
        "<issue_answer_scope>",
        "Your main argument must answer the Issue directly.",
        "Every rule consequent must either be an intermediate fact needed to support your direct answer or the direct answer itself.",
        "</issue_answer_scope>",
        "",
        "<stance_coverage>",
        "Before constructing the argument, silently identify every distinct substantive reason, "
        "requirement, condition, affected group, and tradeoff stated in your stance.",
        "Use as many of them as you can genuinely chain into one coherent line of reasoning "
        "toward your direct answer — do not artificially force unrelated reasons into a single "
        "chain just to mention them; only include a reason where it does real work in the chain.",
        "Keep any material number, threshold, exception, or named affected group from the stance "
        "intact when it is part of a reason you use.",
        "</stance_coverage>",
        "",
        "<no_repetition>",
        "Before answering, compare your planned support against everything your side has already "
        "said earlier in this debate, in any role (an earlier main argument, attack, or defense) — "
        "not only earlier main arguments.",
        "If the only support you can construct substantially restates content your side already "
        "presented earlier — the same facts or reasoning, just reworded or repackaged into a new "
        "argument — set can_generate=NO instead of resubmitting it. This applies even if you "
        "yourself introduced that content in a different role (e.g. as an earlier attack).",
        "</no_repetition>",
    ]

    revision_context = (
        getattr(state, "ag1_revision_context", None)
        if getattr(state, "current_proponent", "AG1") == "AG1"
        else getattr(state, "ag2_revision_context", None)
    )

    if revision_context or rules:
        block = ["", "<revision_context>"]
        if revision_context:
            block += [revision_context, ""]
        else:
            block += ["This is a revision round.", ""]
        block.append(
            "Do not repeat the same main argument unless the defeating reason is resolved."
        )
        if rules:
            block.append("Ground your NEW main argument in the integrated rules below.")
        block.append("</revision_context>")
        lines += block

        if rules:
            lines += [
                "",
                "<integrated_rules>",
                *[f"- {rule}" for rule in rules],
                "</integrated_rules>",
            ]

    lines += [
        "",
        "<response_contract>",
        "If you can construct a main argument with a genuinely new point (see <no_repetition>), "
        "set can_generate=YES and include Argument.",
        "Otherwise, set can_generate=NO and omit Argument.",
        "</response_contract>",
    ]
    return "\n".join(lines)


def _target_block(target: Any, state: Any | None = None) -> str:
    """対象の論証と、（schema は）攻撃の対象を番号で選ぶための一覧を、HumanMessage 内に埋め込む XML 風ブロックにする."""
    mode = str(getattr(state, "output_mode", "schema")) if state is not None else "schema"
    lines = [
        "<target>",
        f"id: {target.id}",
        f"agent: {target.agent}",
        "argument:",
        target.argument,
        "</target>",
    ]
    options = options_block(target, mode)
    if options:
        lines.append(options)
    return "\n".join(lines)


def _target_rules(state: Any | None) -> list[str]:
    """攻撃の種類と、対象の指定の規則（schema は番号で選び、no_schema は対象の本文から書き写す）."""
    mode = str(getattr(state, "output_mode", "schema")) if state is not None else "schema"
    if mode == "no_schema":
        return [
            "- rebut: one claim you make must directly oppose a claim of the target. In Attack, give "
            "the sentence or phrase of <target> that states the claim you oppose.",
            "- undercut: one claim you make must establish that a presumption the target relies on by "
            "default (an exception it takes to be absent) does not hold. In Attack, give the sentence "
            "or phrase of <target> that states that presumption. Merely asserting the opposite of the "
            "target's conclusion, or arguing that the target's framing/scope is inappropriate, does "
            "not qualify.",
            "- Copy the target's words from <target> word for word: do not paraphrase, shorten with "
            "an ellipsis, or combine sentences.",
        ]
    return [
        "- rebut: one conclusion of your argument (any rule's consequent) must contradict one "
        "conclusion of the target. In Attack, give the number of that conclusion in "
        "<target_conclusions>.",
        "- undercut: one conclusion of your argument must establish that an assumption of the target "
        "(a weak_negation entry, of the form 'X is not the case') does not hold, i.e. prove that X "
        "actually holds. In Attack, give the number of that assumption in <target_assumptions>. "
        "Merely asserting the opposite of the target's conclusion, or arguing that the target's "
        "framing/scope is inappropriate, does not qualify. If <target_assumptions> is empty, you "
        "cannot undercut.",
        "- Choose the target only by its number; never copy its text.",
    ]


_CONTENT_REQUIREMENT_BLOCK = "\n".join(
    [
        "<content_requirement>",
        "Your Argument's rules must state a substantive position about the issue itself "
        "(facts, causal claims, values, tradeoffs) — never a verdict about the dialectical "
        'game (e.g. "the target attack fails", "X does not defeat Y", "X\'s conclusion '
        'does not follow from its premises"). Whether your argument defeats the target is '
        "determined separately from the Attack field and the defeat-checking logic, not from "
        "how you phrase your conclusion. State your own substantive position, engaging the "
        "target's specific content (see below) — never phrase the conclusion itself as a "
        "verdict about whether that content holds up.",
        "</content_requirement>",
    ]
)


_DEFEAT_RELATIONS_NOTE = (
    "Each earlier turn is numbered [n]. <defeat_relations> lists which turns of the current thread "
    "have defeated which (and which attempts did not). Take them into account before you write: "
    "see which of your earlier arguments have already defeated, or been defeated by, which; do not "
    "rebuild a move that was already defeated; base your move on what the relations show."
)


def attack_instruction(
    purpose: str,
    target: Any,
    state: Any | None = None,
    main_argument: Any | None = None,
) -> str:
    """攻撃（defeat/counter）の手番に渡す指示文を組む."""
    debate_round = getattr(state, "debate_round", 1) if state is not None else 1
    issue = getattr(state, "question", "") if state is not None else ""
    if purpose == "counter":
        blocks = [
            "<task>",
            f"Round {debate_round}. The opponent's attack below challenges your position on the issue. "
            "State what you hold to be true about the issue that directly answers this specific "
            "challenge — a substantive claim about the issue, not a verdict about whether the attack "
            "succeeds.",
            _DEFEAT_RELATIONS_NOTE,
            "</task>",
            "",
            "<issue>",
            issue,
            "</issue>",
            "",
        ]
        if main_argument is not None:
            blocks += [
                "<your_prior_main_argument>",
                f"id: {main_argument.id}",
                main_argument.argument,
                "</your_prior_main_argument>",
                "",
            ]
        blocks += [
            _target_block(target, state),
            "",
            _CONTENT_REQUIREMENT_BLOCK,
            "",
            "<attack_conditions>",
            "- Your counterargument must defeat the target attack.",
            "- You may use rebut or undercut.",
            *_target_rules(state),
            "</attack_conditions>",
            "",
            "<non_repetition>",
            "You are the proponent: Prakken & Sartor's dialogue game forbids you (but not the "
            "opponent) from making two moves with substantially the same content in this debate — "
            "repeating never helps you, since if the opponent had a move against it the first time, "
            "it has one the second time too.",
            "Before answering, explicitly check your planned counterargument against your original "
            "main argument AND every one of your own earlier counterarguments in this thread — "
            "including ones the opponent has already defeated, and including any of your immediately "
            "preceding retries against this exact same target — even if only the wording, the cited "
            "specifics, or the framing differs. Same underlying conclusion via the same underlying "
            "reasoning counts as a repeat.",
            "A ground is one of the distinct reasons your stance gives for your position (for "
            "example a benefit, a fact about sourcing or evidence, a value). Elaborating a ground "
            "you have already used — adding detail, an example, a more specific mechanism, or "
            "aiming it at a different part of the attack — does not make a new reason.",
            "Record this check in Novelty (filled in before you decide can_defeat): name the "
            "closest of your earlier arguments by its id, and state the new reason your "
            "counterargument adds. If it adds no new reason — only different wording, examples or "
            "framing — set adds_new_reason=NO, and do not make the counterargument.",
            "If the only available counterargument would repeat any of those, set can_defeat=NO.",
            "When more than one distinct reason from your stance could answer this challenge, prefer "
            "the one you have not yet used in this debate — this is how the debate as a whole ends up "
            "covering more of your stance, not any single turn.",
            "</non_repetition>",
            "",
            "<response_contract>",
            "If a valid counterargument exists, set can_defeat=YES and include Argument and Attack.",
            "Otherwise, set can_defeat=NO and omit Argument and Attack.",
            "</response_contract>",
        ]
        return "\n".join(blocks)
    return "\n".join(
        [
            "<task>",
            f"Round {debate_round}. Attack the target argument below (rebut or undercut). Build your "
            "attack from your own stance: state what you hold to be true about the issue that negates "
            "the target argument's specific claim — a substantive claim about the issue, not a "
            "verdict about whether the target argument is defeated.",
            _DEFEAT_RELATIONS_NOTE,
            "</task>",
            "",
            "<issue>",
            issue,
            "</issue>",
            "",
            _target_block(target, state),
            "",
            _CONTENT_REQUIREMENT_BLOCK,
            "",
            "<attack_conditions>",
            "- You may use rebut or undercut.",
            *_target_rules(state),
            "- Supporting a different option does not by itself count as negating the target.",
            "</attack_conditions>",
            "",
            "<response_contract>",
            "If a valid attack exists, set can_defeat=YES and include Argument and Attack.",
            "Otherwise, set can_defeat=NO and omit Argument and Attack.",
            "</response_contract>",
        ]
    )


def integration_instruction(state: Any) -> str:
    """汎化+統合フェーズの HumanMessage を組み立てる."""
    return "\n".join(
        [
            "<task>",
            "Generalize the warrants into reusable criteria, then integrate them into one rule.",
            "</task>",
            "",
            "<warrants>",
            str(state.warrant_result or ""),
            "</warrants>",
            "",
            "<source_stances>",
            "<ag1_stance>",
            str(state.agent1_stance),
            "</ag1_stance>",
            "<ag2_stance>",
            str(state.agent2_stance),
            "</ag2_stance>",
            "</source_stances>",
            "",
            "<response_contract>",
            "Return exactly one integrated rule.",
            "The rule must be applicable to future main arguments.",
            "Do not answer the original Issue.",
            "</response_contract>",
        ]
    )
