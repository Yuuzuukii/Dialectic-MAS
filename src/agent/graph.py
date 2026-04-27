from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Optional

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph

try:
    from .llm import call_llm_messages
    from .prompt import PromptTemplates
    from .schema.outputs.schema import AgentName, ArgumentRecord, ArgumentType, DebateStage
except ImportError:  # pragma: no cover - supports LangGraph file-path loading.
    from llm import call_llm_messages
    from prompt import PromptTemplates
    from schema.outputs.schema import AgentName, ArgumentRecord, ArgumentType, DebateStage

load_dotenv()

MODEL = os.getenv("MODEL", "gpt-5-mini")


@dataclass
class State:
    question: str
    agent1_stance: str
    agent2_stance: str
    max_turns: int = 5
    additional_context: dict[str, Any] = field(default_factory=dict)
    turn_count: int = 0
    active_agent: AgentName = "AG1"
    debate_stage: DebateStage = "ag1_main_thread"
    history: list[ArgumentRecord] = field(default_factory=list)
    current_argument: Optional[ArgumentRecord] = None
    ag1_main_argument: Optional[ArgumentRecord] = None
    ag2_main_argument: Optional[ArgumentRecord] = None
    ag1_pending: bool = False
    ag2_pending: bool = False
    last_can_defeat: Optional[bool] = None
    last_generated_argument: Optional[ArgumentRecord] = None
    last_generated_argument_appended: bool = False
    warrant_result: Optional[str] = None
    generalization_result: Optional[str] = None
    integration_result: Optional[str] = None
    integrated_rule: Optional[str] = None
    justified_argument: Optional[str] = None
    justification_status: Optional[str] = None
    final_rebuttal: Optional[str] = None
    dialogue_history: list[dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None


def _agent_stance(state: State, agent: AgentName) -> str:
    return state.agent1_stance if agent == "AG1" else state.agent2_stance


def _history_text(history: list[ArgumentRecord]) -> str:
    if not history:
        return ""
    lines = ["これまでの議論履歴:"]
    for i, arg in enumerate(history, 1):
        lines.append(f"{i}. [{arg.agent}] {arg.type}: {arg.argument[:200]}...")
    return "\n".join(lines)


def _dialogue_history(history: list[ArgumentRecord]) -> list[dict[str, Any]]:
    return [arg.to_dialogue_dict() for arg in history]


def _record(agent: AgentName, arg_type: ArgumentType, content: str) -> ArgumentRecord:
    return ArgumentRecord(type=arg_type, argument=content, support=[], agent=agent)


def _background_knowledge_text(state: State) -> str:
    if not state.additional_context:
        return ""
    return (
        "\n\nBackgroundKnowledge:\n"
        f"{json.dumps(state.additional_context, ensure_ascii=False, indent=2)}"
    )


def _append_rule_to_stance(stance: str, integrated_rule: str) -> str:
    rule = integrated_rule.strip()
    if not rule or rule in stance:
        return stance
    base = stance.rstrip()
    if not base.endswith("\n"):
        base += "\n"
    return f"{base}{rule}\n"


def _main_argument_for_stage(state: State, stage: str) -> Optional[str]:
    if stage == "ag1_main_justified" and state.ag1_main_argument is not None:
        return state.ag1_main_argument.argument
    if stage == "ag2_main_justified" and state.ag2_main_argument is not None:
        return state.ag2_main_argument.argument
    return None


def _extract_json_from_argument(argument_text: str) -> dict[str, Any]:
    try:
        if "```json" in argument_text:
            json_start = argument_text.find("```json") + 7
            json_end = argument_text.find("```", json_start)
            json_str = argument_text[json_start:json_end].strip()
        elif "```" in argument_text:
            json_start = argument_text.find("```") + 3
            json_end = argument_text.find("```", json_start)
            json_str = argument_text[json_start:json_end].strip()
        else:
            json_start = argument_text.find("{")
            json_end = argument_text.rfind("}") + 1
            json_str = argument_text[json_start:json_end].strip()
        return json.loads(json_str)
    except Exception:
        return {}


def _response_can_defeat(response: str) -> bool:
    data = _extract_json_from_argument(response)
    value = data.get("can_defeat")
    if isinstance(value, str):
        normalized = value.strip().upper()
        if normalized == "YES":
            return True
        if normalized == "NO":
            return False
    return "YES" in response.upper()


def _extract_integrated_rule(integration_result: str) -> Optional[str]:
    data = _extract_json_from_argument(integration_result)
    argument = data.get("Argument", {})
    integration = argument.get("Integration", {})
    rule = integration.get("rule")
    if isinstance(rule, str) and rule.strip():
        cleaned = rule.strip()
        lowered = cleaned.lower()
        if "integrated buying condition" in lowered or "condition 1" in lowered or "condition 2" in lowered:
            return None
        return cleaned
    rules = argument.get("rules", [])
    return None


async def _invoke_agent(system_prompt: str, human_prompt: str) -> str:
    return await call_llm_messages(
        [
            SystemMessage(content=system_prompt),
            HumanMessage(content=human_prompt),
        ],
        MODEL,
    )


async def _construct_main_argument(state: State, agent: AgentName) -> ArgumentRecord:
    response = await _invoke_agent(
        _agent_stance(state, agent),
        f"{PromptTemplates.MAIN_ARGUMENT}\n\nTopic: {state.question}",
    )
    return _record(agent, "main", response)


async def _can_make_defeating_argument(
    state: State,
    agent: AgentName,
    opponent_argument: ArgumentRecord,
) -> tuple[bool, Optional[ArgumentRecord]]:
    history_text = _history_text(state.history)
    full_prompt = (
        f"{history_text}\n\n"
        f"Opponent's argument:\n{opponent_argument.argument}\n\n"
        f"{PromptTemplates.DEFEATING_ARGUMENT}"
    )
    response = await _invoke_agent(_agent_stance(state, agent), full_prompt)
    can_defeat = _response_can_defeat(response)
    if not can_defeat:
        return False, None
    return True, _record(agent, "defeat", response)


async def initialize(state: State) -> dict[str, Any]:
    return {
        "turn_count": 0,
        "active_agent": "AG1",
        "debate_stage": "ag1_main_thread",
        "history": [],
        "current_argument": None,
        "ag1_main_argument": None,
        "ag2_main_argument": None,
        "ag1_pending": False,
        "ag2_pending": False,
        "last_can_defeat": None,
        "last_generated_argument": None,
        "last_generated_argument_appended": False,
        "warrant_result": None,
        "generalization_result": None,
        "integration_result": None,
        "integrated_rule": None,
        "justified_argument": None,
        "justification_status": None,
        "final_rebuttal": None,
        "dialogue_history": [],
        "error": None,
    }


async def ag1_main(state: State) -> dict[str, Any]:
    argument = await _construct_main_argument(state, "AG1")
    history = [argument]
    return {
        "turn_count": 0,
        "active_agent": "AG2",
        "debate_stage": "ag1_main_thread",
        "current_argument": argument,
        "ag1_main_argument": argument,
        "history": history,
        "dialogue_history": _dialogue_history(history),
        "last_can_defeat": None,
        "last_generated_argument": None,
        "last_generated_argument_appended": False,
        "justified_argument": None,
        "justification_status": None,
        "final_rebuttal": None,
    }


async def ag2_attack_ag1(state: State) -> dict[str, Any]:
    if state.current_argument is None:
        return {"error": "No current argument for AG2 to defeat.", "last_can_defeat": False}

    can_defeat, argument = await _can_make_defeating_argument(state, "AG2", state.current_argument)
    if not can_defeat or argument is None:
        stage = "ag1_main_justified"
        return {
            "last_can_defeat": False,
            "last_generated_argument": None,
            "justified_argument": _main_argument_for_stage(state, stage),
            "justification_status": stage,
        }

    return {
        "active_agent": "AG2",
        "turn_count": state.turn_count + 1,
        "last_can_defeat": True,
        "last_generated_argument": argument,
        "last_generated_argument_appended": False,
        "final_rebuttal": argument.argument,
    }


async def ag1_counter_ag2(state: State) -> dict[str, Any]:
    if state.current_argument is None:
        return {"error": "No current argument for AG1 to defeat.", "last_can_defeat": False}

    can_defeat, argument = await _can_make_defeating_argument(state, "AG1", state.current_argument)
    if not can_defeat or argument is None:
        return {"last_can_defeat": False, "last_generated_argument": None}

    history = [*state.history, argument]
    return {
        "active_agent": "AG2",
        "current_argument": argument,
        "history": history,
        "dialogue_history": _dialogue_history(history),
        "last_can_defeat": True,
        "last_generated_argument": argument,
        "last_generated_argument_appended": True,
        "final_rebuttal": argument.argument,
    }


async def ag2_main(state: State) -> dict[str, Any]:
    if state.ag1_main_argument is None:
        return {"error": "Cannot start AG2 main argument without AG1 main argument."}

    preserved_history = [state.ag1_main_argument]
    next_state = State(
        question=state.question,
        agent1_stance=state.agent1_stance,
        agent2_stance=state.agent2_stance,
        max_turns=state.max_turns,
        additional_context=state.additional_context,
        history=preserved_history,
        active_agent="AG2",
    )
    argument = await _construct_main_argument(next_state, "AG2")
    history = [*preserved_history, argument]
    return {
        "active_agent": "AG1",
        "debate_stage": "ag2_main_thread",
        "turn_count": 0,
        "current_argument": argument,
        "ag2_main_argument": argument,
        "history": history,
        "dialogue_history": _dialogue_history(history),
        "last_can_defeat": None,
        "last_generated_argument": None,
        "last_generated_argument_appended": False,
    }


async def ag1_attack_ag2(state: State) -> dict[str, Any]:
    if state.current_argument is None:
        return {"error": "No current argument for AG1 to defeat.", "last_can_defeat": False}

    can_defeat, argument = await _can_make_defeating_argument(state, "AG1", state.current_argument)
    if not can_defeat or argument is None:
        stage = "ag2_main_justified"
        return {
            "last_can_defeat": False,
            "last_generated_argument": None,
            "justified_argument": _main_argument_for_stage(state, stage),
            "justification_status": stage,
        }

    return {
        "turn_count": state.turn_count + 1,
        "last_can_defeat": True,
        "last_generated_argument": argument,
        "last_generated_argument_appended": False,
        "final_rebuttal": argument.argument,
    }


async def ag2_counter_ag1(state: State) -> dict[str, Any]:
    if state.current_argument is None:
        return {"error": "No current argument for AG2 to defeat.", "last_can_defeat": False}

    can_defeat, argument = await _can_make_defeating_argument(state, "AG2", state.current_argument)
    if not can_defeat or argument is None:
        return {"last_can_defeat": False, "last_generated_argument": None}

    history = [*state.history, argument]
    return {
        "active_agent": "AG1",
        "current_argument": argument,
        "history": history,
        "dialogue_history": _dialogue_history(history),
        "last_can_defeat": True,
        "last_generated_argument": argument,
        "last_generated_argument_appended": True,
        "final_rebuttal": argument.argument,
    }


async def early_finish(state: State) -> dict[str, Any]:
    return {
        "dialogue_history": _dialogue_history(state.history),
        "justified_argument": state.justified_argument,
        "justification_status": state.justification_status,
        "final_rebuttal": state.final_rebuttal,
        "integrated_rule": None,
        "agent1_stance": state.agent1_stance,
        "agent2_stance": state.agent2_stance,
    }


async def extract_warrants(state: State) -> dict[str, Any]:
    if state.ag1_main_argument is None or state.ag2_main_argument is None:
        return {"error": "AG1またはAG2のmain argumentが見つかりません"}

    try:
        ag1_json = _extract_json_from_argument(state.ag1_main_argument.argument)
        ag2_json = _extract_json_from_argument(state.ag2_main_argument.argument)
        ag1_last_rule = (
            ag1_json["Argument"]["rules"][-1]
            if ag1_json.get("Argument", {}).get("rules")
            else None
        )
        ag2_last_rule = (
            ag2_json["Argument"]["rules"][-1]
            if ag2_json.get("Argument", {}).get("rules")
            else None
        )
        if not ag1_last_rule or not ag2_last_rule:
            return {"error": "main argumentからruleを抽出できませんでした"}

        warrant_json = {
            "Argument1": {
                "warrant": {
                    "antecedent": {
                        "strong": ag1_last_rule["antecedent"]["strong"],
                    },
                    "consequent": ag1_last_rule["consequent"],
                }
            },
            "Argument2": {
                "warrant": {
                    "antecedent": {
                        "strong": ag2_last_rule["antecedent"]["strong"],
                    },
                    "consequent": ag2_last_rule["consequent"],
                }
            },
        }
        return {"warrant_result": json.dumps(warrant_json, ensure_ascii=False, indent=2)}
    except Exception as exc:
        return {"error": f"Warrant抽出中にエラーが発生しました: {exc}"}


async def generalize(state: State) -> dict[str, Any]:
    if state.warrant_result is None:
        return {"error": "Cannot generalize without warrants."}

    input_text = (
        f"{state.warrant_result}"
        f"{_background_knowledge_text(state)}\n\n"
        f"{PromptTemplates.GENERALIZATION}"
    )
    response = await _invoke_agent(state.agent1_stance, input_text)
    return {"generalization_result": response}


async def integrate(state: State) -> dict[str, Any]:
    if state.warrant_result is None or state.generalization_result is None:
        return {"error": "Cannot integrate without warrants and generalization."}

    input_text = (
        f"{state.warrant_result}\n\n"
        f"{state.generalization_result}"
        f"{_background_knowledge_text(state)}\n\n"
        f"{PromptTemplates.INTEGRATION}"
    )
    response = await _invoke_agent(state.agent1_stance, input_text)
    integrated_rule = _extract_integrated_rule(response)
    if integrated_rule is None:
        return {"error": "統合結果から新しいルールを抽出できませんでした"}

    return {
        "integration_result": response,
        "integrated_rule": integrated_rule,
        "agent1_stance": _append_rule_to_stance(state.agent1_stance, integrated_rule),
        "dialogue_history": _dialogue_history(state.history),
    }


async def finish_with_error(state: State) -> dict[str, Any]:
    return {
        "dialogue_history": _dialogue_history(state.history),
        "justified_argument": state.justified_argument,
        "justification_status": state.justification_status,
        "final_rebuttal": state.final_rebuttal,
        "integrated_rule": state.integrated_rule,
        "agent1_stance": state.agent1_stance,
        "agent2_stance": state.agent2_stance,
        "error": state.error,
    }


def route_after_ag2_attack_ag1(state: State) -> str:
    if state.error:
        return "finish_with_error"
    if state.last_can_defeat is False:
        return "early_finish"
    return "ag2_main"


def route_after_ag1_attack_ag2(state: State) -> str:
    if state.error:
        return "finish_with_error"
    return "extract_warrants"


def route_after_integration_step(state: State) -> str:
    if state.error:
        return "finish_with_error"
    return "next"


graph = (
    StateGraph(State)
    .add_node("initialize", initialize)
    .add_node("ag1_main", ag1_main)
    .add_node("ag2_attack_ag1", ag2_attack_ag1)
    .add_node("ag2_main", ag2_main)
    .add_node("ag1_attack_ag2", ag1_attack_ag2)
    .add_node("extract_warrants", extract_warrants)
    .add_node("generalize", generalize)
    .add_node("integrate", integrate)
    .add_node("early_finish", early_finish)
    .add_node("finish_with_error", finish_with_error)
    .add_edge(START, "initialize")
    .add_edge("initialize", "ag1_main")
    .add_edge("ag1_main", "ag2_attack_ag1")
    .add_conditional_edges(
        "ag2_attack_ag1",
        route_after_ag2_attack_ag1,
        {
            "early_finish": "early_finish",
            "ag2_main": "ag2_main",
            "finish_with_error": "finish_with_error",
        },
    )
    .add_edge("ag2_main", "ag1_attack_ag2")
    .add_conditional_edges(
        "ag1_attack_ag2",
        route_after_ag1_attack_ag2,
        {
            "extract_warrants": "extract_warrants",
            "finish_with_error": "finish_with_error",
        },
    )
    .add_conditional_edges(
        "extract_warrants",
        route_after_integration_step,
        {"next": "generalize", "finish_with_error": "finish_with_error"},
    )
    .add_conditional_edges(
        "generalize",
        route_after_integration_step,
        {"next": "integrate", "finish_with_error": "finish_with_error"},
    )
    .add_edge("integrate", "ag1_main")
    .add_edge("early_finish", END)
    .add_edge("finish_with_error", END)
    .compile(name="Dialect MAS")
)
