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
- Your values and priorities come from your stance. You may use general knowledge to identify real-world options that satisfy them.
</grounding>"""

_ARGUMENT_FORMAT = """\
<argument_format>
- An argument is a finite sequence of rules r_1, ..., r_n.
- Each rule has an antecedent (strong premises + weak_negation assumptions) and a consequent it derives.
- Every rule must have at least one explicit strong or weak_negation antecedent; never derive a consequent from an empty antecedent.
- Each consequent must follow directly from its antecedents, with no implicit logical leap.
- Strong antecedents of r_i (i > 1) must be consequents of earlier rules; every non-final consequent must reappear as a strong antecedent of a later rule.
- Use as few rules as possible; a single rule suffices when your stance directly supports the conclusion.
</argument_format>"""

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


def _system(*blocks: str) -> str:
    """XML タグ付きブロックを空行区切りで連結して 1 つの system プロンプトにする."""
    return "\n\n".join(block.strip() for block in blocks if block and block.strip())


class PromptTemplates:
    """各ノードが参照する SYSTEM プロンプト文字列の名前空間."""

    # ---- System: argument-construction framework + task definitions ----
    MAIN_ARGUMENT_SYSTEM = _system(
        "<task>\nConstruct an argument for your position on the Issue.\n</task>",
        _PROTOCOL_FLOW,
        _HISTORY_FORMAT,
        _GROUNDING,
        _ARGUMENT_FORMAT,
        "<conclusion>\n"
        "- The final conclusion must clearly express your opinion on the Issue, stated in a concise and specific way.\n"
        "</conclusion>",
        "<output>\n"
        "- If you can construct such an argument: set can_generate=YES and include Argument.\n"
        "- Otherwise: set can_generate=NO and omit Argument.\n"
        "</output>",
    )

    DEFEATING_ARGUMENT_SYSTEM = _system(
        "<task>\nConstruct a defeating argument against the target argument.\n</task>",
        _PROTOCOL_FLOW,
        _HISTORY_FORMAT,
        _GROUNDING,
        _ATTACK_TYPES,
        _ARGUMENT_FORMAT,
        "<defeat_conditions>\n"
        "- rebut may target only an exact statement in Conc(target); undercut may target only an exact statement in Ass(target), never a strong premise.\n"
        "- For a rebut, your rules must directly derive the negation of the targeted conclusion. Supporting a different option does not by itself negate the target.\n"
        "- Do not declare an attack whose targeted statement does not appear in the required field.\n"
        "- If the negation cannot be directly derived, set can_defeat=NO.\n"
        "</defeat_conditions>",
        "<output>\n"
        "- If a valid attack exists: set can_defeat=YES, and include Argument and Attack (method + exact targeted statement).\n"
        "- Otherwise: set can_defeat=NO and omit Argument and Attack.\n"
        "</output>",
    )

    COUNTER_ARGUMENT_SYSTEM = _system(
        "<task>\nConstruct a counterargument against the target argument that defends your position.\n</task>",
        _PROTOCOL_FLOW,
        _HISTORY_FORMAT,
        _GROUNDING,
        _ATTACK_TYPES,
        _ARGUMENT_FORMAT,
        "<non_repetition>\n"
        "- Do not derive the same conclusion from substantially the same rules or warrant as any of your previous arguments.\n"
        "- A counterargument that merely restates your original main argument is not allowed.\n"
        "- If the only available counterargument would repeat a previous argument, set can_defeat=NO.\n"
        "</non_repetition>",
        "<output>\n"
        "- If a valid attack exists: set can_defeat=YES, and include Argument and Attack (method + exact targeted statement).\n"
        "- Otherwise: set can_defeat=NO and omit Argument and Attack.\n"
        "</output>",
    )

    UNDERCUT_SYSTEM = _system(
        "<task>\nConstruct an undercutting argument against the target argument.\n</task>",
        _PROTOCOL_FLOW,
        _HISTORY_FORMAT,
        _GROUNDING,
        _ATTACK_TYPES,
        _ARGUMENT_FORMAT,
        "<output>\n"
        "- If a conclusion of your argument can explicitly negate an assumption (Ass) of the target: set can_undercut=YES and include Argument.\n"
        "- Otherwise: set can_undercut=NO and omit Argument.\n"
        "</output>",
    )

    GENERALIZATION_SYSTEM = _system(
        "<task>\nGeneralize each warrant into a reusable abstract criterion.\n</task>",
        "<rules>\n"
        "- Abstract away from issue-specific entities.\n"
        "- For each warrant, identify the underlying value or principle that makes it rationally compelling.\n"
        "- Express that principle as the criterion's conditions (strong) and conclusion (consequent).\n"
        "- Record the principle name explicitly.\n"
        "</rules>",
    )

    INTEGRATION_SYSTEM = _system(
        "<task>\nIntegrate the generalized criteria into one reusable rule.\n</task>",
        "<rules>\n"
        "- Identify the shared higher-level principle that unifies the underlying values of all criteria.\n"
        "- Express that principle as a single abstract rule whose antecedent covers each criterion as an alternative sufficient condition (OR).\n"
        "- The rule should be more abstract than any individual criterion, not merely a list of them.\n"
        "- Output one rule applicable to future arguments.\n"
        "</rules>",
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


def compose_system(stance: str, task_system: str) -> str:
    """エージェントのスタンス（役割）とタスク定義を 1 つの system プロンプトに結合する."""
    stance = (stance or "").strip()
    task_system = task_system.strip()
    if not stance:
        return task_system
    return f"{stance}\n\n{task_system}"


def agent_system(stance: str, agent: AgentName, task_system: str) -> str:
    """エージェント identity + stance + タスク定義を 1 つの system プロンプトにする."""
    identity = (
        "<identity>\n"
        f'You are {agent} in this debate. In the message history, turns whose agent/name is "{agent}" '
        "are your own past turns; the other agent is your opponent.\n"
        "</identity>"
    )
    return f"{identity}\n\n{compose_system(stance, task_system)}"


def main_instruction(state: Any) -> str:
    """主張生成の手番に渡す指示文（Issue + 改訂ラウンドなら統合ルール）を組む."""
    issue = state.question
    rules = getattr(state, "integrated_rules", []) or []
    debate_round = getattr(state, "debate_round", 1)
    lines = [
        f"Round {debate_round}. Construct your main argument for the Issue.",
        f"Issue: {issue}",
    ]
    if rules:
        lines += [
            "",
            "This is a revision round: your earlier main arguments (shown in the history) were defeated.",
            "Ground your NEW main argument in the integrated rules below, make it different from every earlier",
            "main argument, and ensure it is not vulnerable to the same attacks that defeated them:",
            *[f"- {rule}" for rule in rules],
        ]
    return "\n".join(lines)


def attack_instruction(purpose: str, target_id: str) -> str:
    """攻撃（defeat/counter）の手番に渡す指示文を組む."""
    if purpose == "counter":
        return (
            "Construct a counterargument that defends your main argument against the latest attack "
            f"(id={target_id}) shown in the history."
        )
    return (
        "Construct a defeating argument against your opponent's latest argument "
        f"(id={target_id}) shown in the history."
    )


def undercut_instruction(target_id: str) -> str:
    """Undercut の手番に渡す指示文を組む."""
    return (
        f"Construct an undercutting argument against the argument (id={target_id}) shown in the history, "
        "by negating one of its assumptions (Ass)."
    )
