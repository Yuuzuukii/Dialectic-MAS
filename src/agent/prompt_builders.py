from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

try:
    from .prompts import PromptTemplates
    from .schema.state import ArgumentRecord
    from .schema.types import AgentName
except ImportError:  # pragma: no cover - supports LangGraph file-path loading.
    from prompts import PromptTemplates
    from schema.state import ArgumentRecord
    from schema.types import AgentName


def _stance(state: Any, agent: AgentName) -> str:
    return state.agent1_stance if agent == "AG1" else state.agent2_stance


def compose_system(stance: str, task_system: str) -> str:
    """エージェントのスタンス（役割）とタスク定義を 1 つの system プロンプトに結合する。"""
    stance = (stance or "").strip()
    task_system = task_system.strip()
    if not stance:
        return task_system
    return f"{stance}\n\n{task_system}"


def _agent_system(state: Any, agent: AgentName, task_system: str) -> str:
    """エージェント identity + stance + タスク定義を 1 つの system プロンプトにする。"""
    identity = (
        "<identity>\n"
        f'You are {agent} in this debate. In the message history, turns whose agent/name is "{agent}" '
        "are your own past turns; the other agent is your opponent.\n"
        "</identity>"
    )
    return f"{identity}\n\n{compose_system(_stance(state, agent), task_system)}"


def render_history(history: list[ArgumentRecord]) -> list[BaseMessage]:
    """state.history を読み取り専用で受け取り、視点非依存のメッセージ列に変換する。

    各 turn は AIMessage（assistant）とし、`name` に発言者 (AG1/AG2) を載せて区別する。
    content は ArgumentRecord.message_content()（round/phase/agent/attack/status + Argument の JSON）。
    state は一切変更しない（毎回まっさらな新リストを返す）。
    """
    return [
        AIMessage(content=record.message_content(), name=record.agent)
        for record in history
    ]


def _main_instruction(state: Any) -> str:
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


def _attack_instruction(purpose: str, target: ArgumentRecord) -> str:
    if purpose == "defend_main":
        return (
            "Construct a counterargument that defends your main argument against the latest attack "
            f"(id={target.id}) shown in the history."
        )
    return (
        "Construct a defeating argument against your opponent's latest argument "
        f"(id={target.id}) shown in the history."
    )


def _undercut_instruction(target: ArgumentRecord) -> str:
    return (
        f"Construct an undercutting argument against the argument (id={target.id}) shown in the history, "
        "by negating one of its assumptions (Ass)."
    )


def build_main_argument_messages(state: Any, agent: AgentName) -> list[BaseMessage]:
    return [
        SystemMessage(content=_agent_system(state, agent, PromptTemplates.MAIN_ARGUMENT_SYSTEM)),
        *render_history(state.history),
        HumanMessage(content=_main_instruction(state)),
    ]


def build_attack_messages(
    state: Any,
    attacker: AgentName,
    target: ArgumentRecord,
    *,
    purpose: str,
) -> list[BaseMessage]:
    task_system = (
        PromptTemplates.COUNTER_ARGUMENT_SYSTEM
        if purpose == "defend_main"
        else PromptTemplates.DEFEATING_ARGUMENT_SYSTEM
    )
    return [
        SystemMessage(content=_agent_system(state, attacker, task_system)),
        *render_history(state.history),
        HumanMessage(content=_attack_instruction(purpose, target)),
    ]


def build_undercut_messages(
    state: Any, attacker: AgentName, target: ArgumentRecord
) -> list[BaseMessage]:
    return [
        SystemMessage(content=_agent_system(state, attacker, PromptTemplates.UNDERCUT_CHECK_SYSTEM)),
        *render_history(state.history),
        HumanMessage(content=_undercut_instruction(target)),
    ]


# 合成（generalize / integrate）は対話履歴を既にテキストで全量持つメタタスクのため、
# 視点相対メッセージ化はせず従来どおり (system, user) 文字列で組む。
def build_generalization_prompt(
    warrant_result: str, conversation_history: str
) -> tuple[str, str]:
    system = PromptTemplates.GENERALIZATION_SYSTEM.strip()
    user = f"## Warrants\n{warrant_result}\n\n## Dialogue History\n{conversation_history}"
    return system, user


def build_integration_prompt(
    warrant_result: str, generalization_result: str
) -> tuple[str, str]:
    system = PromptTemplates.INTEGRATION_SYSTEM.strip()
    user = f"{warrant_result}\n\n{generalization_result}"
    return system, user
