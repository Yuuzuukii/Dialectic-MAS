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

# ---- 共有ブロック（複数テンプレートで再利用） ----

_GROUNDING = """\
<grounding>
- Your values and priorities come from your stance.
- Your argument must be grounded in that stance.
- You may use general knowledge only when it helps identify real-world options or reasons that satisfy your stance.
</grounding>"""

_ARGUMENTATION_RULES = """\
<argumentation_rules>
- State the premises and assumptions you rely on.
- Do not introduce new factual claims as strong premises; each strong premise must be stated or directly derived from your stance, the target argument, prior dialogue history, or integrated rules.
- The conclusion must follow directly from the stated reasoning, with no implicit logical leap.
- The final conclusion must clearly express your opinion on the Issue in a concise and specific way.
- Be concise; do not pad the reasoning with repetition.
</argumentation_rules>"""

_SCHEMA_OVERLAY = """\
<schema_overlay>
Represent Argument as a structured object consisting of rules, Conc, and Ass.
- rules is a finite sequence of rules r_1, ..., r_n.
- Each rule has an antecedent and a consequent.
- Antecedents may contain strong premises and weak_negation assumptions.
- Every rule must have at least one explicit strong or weak_negation antecedent; never derive a consequent from an empty antecedent.
- Strong antecedents of r_i (i > 1) must be consequents of earlier rules.
- Every non-final consequent must reappear as a strong antecedent of a later rule.
- Conc contains the conclusions derived by the rules.
- Ass contains the weak_negation assumptions used by the rules.
- Use as few rules as possible; a single rule suffices when your stance directly supports the conclusion.
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
The debate ends when a main is justified, or when the round limit is reached (then a provisional, no-consensus
answer is produced from the integrated rules).
</protocol_flow>"""

_HISTORY_FORMAT = """\
<history_format>
Prior turns of this debate are provided as preceding messages. Each message's content is a JSON object:
  {"id", "round", "phase", "agent", ["status"], ["attack","target_id","target_statement"], "Argument": {"rules","Conc","Ass"}}
- "phase" is one of main / defeat / counter; "status" (on a main, when known) is its thread outcome above.
- "attack"/"target_id"/"target_statement" (on defeat/counter) show exactly what was attacked.
- A message whose "agent"/name equals YOUR identity is your own past turn; the other agent's are your opponent's.
Use this history to avoid repeating defeated moves and to stay consistent with the current round and integrated rules.
</history_format>"""

_HISTORY_FORMAT_FREE = """\
<history_format>
Prior turns of this debate are provided as preceding messages. Each message's content is a JSON object:
  {"id", "round", "phase", "agent", ["status"], ["attack","target_id","target_statement"], "Argument": "<free-text argument>"}
- "phase" is one of main / defeat / counter; "status" (on a main, when known) is its thread outcome above.
- "attack"/"target_id"/"target_statement" (on defeat/counter) show exactly what was attacked.
- A message whose "agent"/name equals YOUR identity is your own past turn; the other agent's are your opponent's.
Use this history to avoid repeating defeated moves and to stay consistent with the current round and integrated rules.
</history_format>"""


def _system(*blocks: str) -> str:
    """XML タグ付きブロックを空行区切りで連結して 1 つの system プロンプトにする."""
    return "\n\n".join(block.strip() for block in blocks if block and block.strip())


class PromptTemplates:
    """各ノードが参照する SYSTEM プロンプト文字列の名前空間."""

    # ---- System: shared argument-construction framework ----
    ARGUMENT_SYSTEM_NO_SCHEMA = _system(
        _GROUNDING,
        _ARGUMENTATION_RULES,
    )

    ARGUMENT_SYSTEM = _system(
        ARGUMENT_SYSTEM_NO_SCHEMA,
        _SCHEMA_OVERLAY,
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

    _GENERALIZATION_SYSTEM_BASE = _system(
        "<role>\n"
        "You are AG1 in this debate.\n"
        "You now act as the synthesis operator for the debate.\n"
        "Your task is to generalize each side's warrant into a reusable criterion for future arguments.\n"
        "</role>",
        "<stance>\n{stance}\n</stance>",
        "<generalization_principles>\n"
        "- Treat both sides' warrants as inputs to be preserved at the level of value or principle.\n"
        "- Do not discard AG2's warrant merely because it conflicts with AG1's stance.\n"
        "- Do not simply restate AG1's own warrant as the synthesis result.\n"
        "- Abstract away from issue-specific entities, examples, and one-off facts.\n"
        "- Preserve the condition under which each warrant is rationally compelling.\n"
        "- Preserve the conclusion type supported by each warrant.\n"
        "- Do not choose a winner between the two sides during generalization.\n"
        "- Do not produce a final answer to the original Issue.\n"
        "</generalization_principles>",
    )

    GENERALIZATION_SYSTEM_NO_SCHEMA = _GENERALIZATION_SYSTEM_BASE

    GENERALIZATION_SYSTEM = _system(
        _GENERALIZATION_SYSTEM_BASE,
        "<schema_overlay>\n"
        "Represent each generalized criterion as a structured object.\n"
        "- strong: generalized condition(s) under which the criterion applies.\n"
        "- consequent: the generalized conclusion supported by those conditions.\n"
        "- principle: a short name or phrase for the underlying value or principle.\n"
        "</schema_overlay>",
    )

    _INTEGRATION_SYSTEM_BASE = _system(
        "<role>\n"
        "You are AG1 in this debate.\n"
        "You now act as the synthesis operator for the debate.\n"
        "Your task is to integrate generalized criteria into one reusable rule for the next debate round.\n"
        "</role>",
        "<stance>\n{stance}\n</stance>",
        "<integration_principles>\n"
        "- The integrated rule must preserve every generalized criterion as an alternative sufficient condition.\n"
        "- The integrated rule must be more abstract than any individual criterion.\n"
        "- The integrated rule must not merely list the criteria without unifying them.\n"
        "- The integrated rule must be usable by either side in the next round.\n"
        "- Do not discard AG2's generalized criterion merely because it conflicts with AG1's stance.\n"
        "- Do not simply restate AG1's own criterion as the integrated rule.\n"
        "- Do not produce a final answer to the original Issue.\n"
        "</integration_principles>",
    )

    INTEGRATION_SYSTEM_NO_SCHEMA = _INTEGRATION_SYSTEM_BASE

    INTEGRATION_SYSTEM = _system(
        _INTEGRATION_SYSTEM_BASE,
        "<schema_overlay>\n"
        "Represent the integrated rule as one structured reusable rule.\n"
        "- The antecedent should cover each generalized criterion as an alternative sufficient condition.\n"
        "- Use OR to combine alternative sufficient conditions.\n"
        "- The consequent should state the shared generalized conclusion.\n"
        "- The result must be one rule, not multiple unrelated rules.\n"
        "</schema_overlay>",
    )

    FINAL_ANSWER_SYSTEM = _system(
        "<task>\nYou participated in a dialectical debate on a question, and your argument was justified. Write the final answer.\n</task>",
        "<style>\n"
        "- Write a concise answer to the question in natural language from your perspective.\n"
        "- State your position clearly and briefly explain the key reasoning that was upheld through the debate.\n"
        "</style>",
    )

    # 合意（justified な決着）に至らないままラウンド上限に達したときの暫定回答。
    FINAL_ANSWER_NO_CONSENSUS_SYSTEM = _system(
        "<context>\n"
        "The dialectical debate reached its round limit WITHOUT either side's argument being justified, so no consensus was reached.\n"
        "</context>",
        "<task>\nProduce a provisional, best-effort answer grounded in the integrated rules that neither side could deny.\n</task>",
        "<style>\n"
        "- Make it explicit that this is a provisional answer and that no agreement was reached in the debate.\n"
        "- Base your reasoning on the integrated rules and the provisional main argument built on them.\n"
        "- Be concise: state the provisional position and the shared rules it rests on.\n"
        "</style>",
    )

    # ---- User: per-turn variable input ----
    FINAL_ANSWER_USER = """
Question: {question}

Dialogue history:
{dialogue_history}

Your justified argument:
{justified_argument}
"""

    FINAL_ANSWER_NO_CONSENSUS_USER = """
Question: {question}

No consensus was reached within the debate limit. The following integrated rules were agreed as undeniable by both sides:
{integrated_rules}

Dialogue history:
{dialogue_history}

Provisional main argument built on the integrated rules:
{justified_argument}
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
        "If you can construct a main argument, set can_generate=YES and include Argument.",
        "Otherwise, set can_generate=NO and omit Argument.",
        "</response_contract>",
    ]
    return "\n".join(lines)


def _target_block(target: Any) -> str:
    """ArgumentRecord target を HumanMessage 内に埋め込む短い XML ブロックへ変換する."""
    return "\n".join(
        [
            "<target>",
            f"id: {target.id}",
            f"agent: {target.agent}",
            "argument:",
            target.argument,
            "</target>",
        ]
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
            f"Round {debate_round}. Construct a counterargument that defends your prior main argument against the target attack.",
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
            _target_block(target),
            "",
            "<attack_conditions>",
            "- Your counterargument must defeat the target attack.",
            "- You may use rebut or undercut.",
            "- rebut: your argument must directly negate the target's stated conclusion.",
            "- undercut: your argument must directly negate an assumption the target relies on.",
            "- Do not attack a claim or assumption that is not present in the target argument.",
            "</attack_conditions>",
            "",
            "<non_repetition>",
            "Do not merely restate your original main argument.",
            "Do not derive the same conclusion from substantially the same reasoning as any of your previous arguments.",
            "If the only available counterargument would repeat a previous argument, set can_defeat=NO.",
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
            f"Round {debate_round}. Construct a defeating argument against the target argument.",
            "</task>",
            "",
            "<issue>",
            issue,
            "</issue>",
            "",
            _target_block(target),
            "",
            "<attack_conditions>",
            "- You may use rebut or undercut.",
            "- rebut: your argument must directly negate the target's stated conclusion.",
            "- undercut: your argument must directly negate an assumption the target relies on.",
            "- Do not attack a claim or assumption that is not present in the target argument.",
            "- Supporting a different option does not by itself count as negating the target.",
            "</attack_conditions>",
            "",
            "<response_contract>",
            "If a valid attack exists, set can_defeat=YES and include Argument and Attack.",
            "Otherwise, set can_defeat=NO and omit Argument and Attack.",
            "</response_contract>",
        ]
    )


def undercut_instruction(target: Any, state: Any | None = None) -> str:
    """Undercut の手番に渡す指示文を組む."""
    debate_round = getattr(state, "debate_round", 1) if state is not None else 1
    issue = getattr(state, "question", "") if state is not None else ""
    return "\n".join(
        [
            "<task>",
            f"Round {debate_round}. Construct an undercutting argument against the target argument.",
            "</task>",
            "",
            "<issue>",
            issue,
            "</issue>",
            "",
            _target_block(target),
            "",
            "<response_contract>",
            "If your argument can explicitly negate an assumption the target relies on, set can_undercut=YES and include Argument.",
            "Otherwise, set can_undercut=NO and omit Argument.",
            "</response_contract>",
        ]
    )


def generalization_instruction(state: Any) -> str:
    """汎化フェーズの HumanMessage を組み立てる."""
    return "\n".join(
        [
            "<task>",
            "Generalize the warrants into reusable criteria.",
            "</task>",
            "",
            "<warrants>",
            str(state.warrant_result or ""),
            "</warrants>",
            "",
            "<response_contract>",
            "Return generalized criteria only.",
            "Do not return an integrated rule yet.",
            "Do not answer the original Issue.",
            "</response_contract>",
        ]
    )


def integration_instruction(state: Any) -> str:
    """統合フェーズの HumanMessage を組み立てる."""
    return "\n".join(
        [
            "<task>",
            "Integrate the generalized criteria into one reusable rule.",
            "</task>",
            "",
            "<warrants>",
            str(state.warrant_result or ""),
            "</warrants>",
            "",
            "<generalized_criteria>",
            str(state.generalization_result or ""),
            "</generalized_criteria>",
            "",
            "<response_contract>",
            "Return exactly one integrated rule.",
            "The rule must be applicable to future main arguments.",
            "Do not answer the original Issue.",
            "</response_contract>",
        ]
    )
