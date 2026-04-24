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
    characterization_result: Optional[str] = None
    generalization_result: Optional[str] = None
    answer: Optional[str] = None
    synthesis: Optional[dict[str, Any]] = None
    dialogue_history: list[dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None


def _agent_stance(state: State, agent: AgentName) -> str:
    return state.agent1_stance if agent == "AG1" else state.agent2_stance


def _opponent(agent: AgentName) -> AgentName:
    return "AG2" if agent == "AG1" else "AG1"


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
    if _is_rebut_without_weak_negation(opponent_argument):
        return False, None

    history_text = _history_text(state.history)
    full_prompt = (
        f"{history_text}\n\n"
        f"Opponent's argument:\n{opponent_argument.argument}\n\n"
        f"{PromptTemplates.DEFEATING_ARGUMENT}"
    )
    response = await _invoke_agent(_agent_stance(state, agent), full_prompt)
    can_defeat = "YES" in response.upper() or "yes" in response
    if not can_defeat:
        return False, None
    return True, _record(agent, "defeat", response)


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


def _has_valid_weak_negation(weak_negation_list: Any) -> bool:
    if not weak_negation_list:
        return False
    for item in weak_negation_list:
        if item and item != [] and item != "":
            return True
    return False


def _is_rebut_without_weak_negation(opponent_argument: ArgumentRecord) -> bool:
    if opponent_argument.type == "main":
        return False

    json_data = _extract_json_from_argument(opponent_argument.argument)
    if not json_data:
        return False

    attack_type = json_data.get("Argument", {}).get("attack", "")
    if attack_type.lower() != "rebut":
        return False

    ass_list = json_data.get("Argument", {}).get("Ass", [])
    has_valid_ass = _has_valid_weak_negation(ass_list)

    rules = json_data.get("Argument", {}).get("rules", [])
    has_valid_weak_negation_in_rules = False
    for rule in rules:
        weak_negation = rule.get("antecedent", {}).get("weak_negation", [])
        if _has_valid_weak_negation(weak_negation):
            has_valid_weak_negation_in_rules = True
            break

    return not has_valid_ass and not has_valid_weak_negation_in_rules


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
        "characterization_result": None,
        "generalization_result": None,
        "answer": None,
        "synthesis": None,
        "dialogue_history": [],
        "error": None,
    }


async def ag1_main(state: State) -> dict[str, Any]:
    argument = await _construct_main_argument(state, "AG1")
    history = [argument]
    return {
        "active_agent": "AG2",
        "current_argument": argument,
        "ag1_main_argument": argument,
        "history": history,
        "dialogue_history": _dialogue_history(history),
    }


async def ag2_attack_ag1(state: State) -> dict[str, Any]:
    if state.current_argument is None:
        return {"error": "No current argument for AG2 to defeat.", "last_can_defeat": False}

    can_defeat, argument = await _can_make_defeating_argument(state, "AG2", state.current_argument)
    if not can_defeat or argument is None:
        return {"last_can_defeat": False, "last_generated_argument": None}

    if state.turn_count >= state.max_turns:
        return {
            "ag1_pending": True,
            "last_can_defeat": True,
            "last_generated_argument": argument,
            "last_generated_argument_appended": False,
        }

    history = [*state.history, argument]
    return {
        "active_agent": "AG1",
        "current_argument": argument,
        "history": history,
        "dialogue_history": _dialogue_history(history),
        "turn_count": state.turn_count + 1,
        "last_can_defeat": True,
        "last_generated_argument": argument,
        "last_generated_argument_appended": True,
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
        return {"last_can_defeat": False, "last_generated_argument": None}

    if state.turn_count >= state.max_turns:
        return {
            "last_can_defeat": True,
            "last_generated_argument": argument,
            "last_generated_argument_appended": False,
        }

    history = [*state.history, argument]
    return {
        "active_agent": "AG2",
        "current_argument": argument,
        "history": history,
        "dialogue_history": _dialogue_history(history),
        "turn_count": state.turn_count + 1,
        "last_can_defeat": True,
        "last_generated_argument": argument,
        "last_generated_argument_appended": True,
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
    }


async def early_finish(state: State) -> dict[str, Any]:
    return {
        "answer": None,
        "synthesis": None,
        "dialogue_history": _dialogue_history(state.history),
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
                        "weak_negation": ag1_last_rule["antecedent"].get("weak_negation", []),
                    },
                    "consequent": ag1_last_rule["consequent"],
                }
            },
            "Argument2": {
                "warrant": {
                    "antecedent": {
                        "strong": ag2_last_rule["antecedent"]["strong"],
                        "weak_negation": ag2_last_rule["antecedent"].get("weak_negation", []),
                    },
                    "consequent": ag2_last_rule["consequent"],
                }
            },
        }
        return {"warrant_result": json.dumps(warrant_json, ensure_ascii=False, indent=2)}
    except Exception as exc:
        return {"error": f"Warrant抽出中にエラーが発生しました: {exc}"}


async def characterize(state: State) -> dict[str, Any]:
    if state.warrant_result is None:
        return {"error": "Cannot characterize without warrants."}

    background_knowledge_json = ""
    if state.additional_context:
        background_knowledge_json = (
            f"\n\nBackgroundKnowledge:\n"
            f"{json.dumps(state.additional_context, ensure_ascii=False, indent=2)}"
        )

    input_text = f"{state.warrant_result}{background_knowledge_json}\n\n{PromptTemplates.CHARACTERIZATION}"
    response = await _invoke_agent(state.agent1_stance, input_text)
    return {"characterization_result": response}


async def generalize(state: State) -> dict[str, Any]:
    if state.characterization_result is None:
        return {"error": "Cannot generalize without characterization."}

    input_text = f"{state.characterization_result}\n\n{PromptTemplates.GENERALIZATION}"
    response = await _invoke_agent(state.agent1_stance, input_text)
    return {"generalization_result": response}


async def answer(state: State) -> dict[str, Any]:
    if state.warrant_result is None or state.generalization_result is None:
        return {"error": "Cannot answer without warrants and generalization."}

    input_text = f"{state.warrant_result}\n\n{state.generalization_result}\n\n{PromptTemplates.ANSWER}"
    response = await _invoke_agent(state.agent1_stance, input_text)
    synthesis = {"final_answer": response}

    return {
        "answer": synthesis["final_answer"],
        "synthesis": synthesis,
        "dialogue_history": _dialogue_history(state.history),
    }


async def finish_with_error(state: State) -> dict[str, Any]:
    return {
        "answer": None,
        "synthesis": None,
        "dialogue_history": _dialogue_history(state.history),
    }


def route_after_ag2_attack_ag1(state: State) -> str:
    if state.error:
        return "finish_with_error"
    if state.last_can_defeat is False:
        return "early_finish"
    if state.ag1_pending:
        return "ag2_main"
    return "ag1_counter_ag2"


def route_after_ag1_counter_ag2(state: State) -> str:
    if state.error:
        return "finish_with_error"
    if state.last_can_defeat is False:
        return "ag2_main"
    return "ag2_attack_ag1"


def route_after_ag1_attack_ag2(state: State) -> str:
    if state.error:
        return "finish_with_error"
    if state.last_can_defeat is False:
        return "extract_warrants"
    if state.turn_count >= state.max_turns and not state.last_generated_argument_appended:
        return "extract_warrants"
    return "ag2_counter_ag1"


def route_after_ag2_counter_ag1(state: State) -> str:
    if state.error:
        return "finish_with_error"
    if state.last_can_defeat is False:
        return "extract_warrants"
    return "ag1_attack_ag2"


def route_after_synthesis_step(state: State) -> str:
    if state.error:
        return "finish_with_error"
    return "next"


graph = (
    StateGraph(State)
    .add_node("initialize", initialize)
    .add_node("ag1_main", ag1_main)
    .add_node("ag2_attack_ag1", ag2_attack_ag1)
    .add_node("ag1_counter_ag2", ag1_counter_ag2)
    .add_node("ag2_main", ag2_main)
    .add_node("ag1_attack_ag2", ag1_attack_ag2)
    .add_node("ag2_counter_ag1", ag2_counter_ag1)
    .add_node("extract_warrants", extract_warrants)
    .add_node("characterize", characterize)
    .add_node("generalize", generalize)
    .add_node("answer", answer)
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
            "ag1_counter_ag2": "ag1_counter_ag2",
            "ag2_main": "ag2_main",
            "finish_with_error": "finish_with_error",
        },
    )
    .add_conditional_edges(
        "ag1_counter_ag2",
        route_after_ag1_counter_ag2,
        {
            "ag2_main": "ag2_main",
            "ag2_attack_ag1": "ag2_attack_ag1",
            "finish_with_error": "finish_with_error",
        },
    )
    .add_edge("ag2_main", "ag1_attack_ag2")
    .add_conditional_edges(
        "ag1_attack_ag2",
        route_after_ag1_attack_ag2,
        {
            "extract_warrants": "extract_warrants",
            "ag2_counter_ag1": "ag2_counter_ag1",
            "finish_with_error": "finish_with_error",
        },
    )
    .add_conditional_edges(
        "ag2_counter_ag1",
        route_after_ag2_counter_ag1,
        {
            "extract_warrants": "extract_warrants",
            "ag1_attack_ag2": "ag1_attack_ag2",
            "finish_with_error": "finish_with_error",
        },
    )
    .add_conditional_edges(
        "extract_warrants",
        route_after_synthesis_step,
        {"next": "characterize", "finish_with_error": "finish_with_error"},
    )
    .add_conditional_edges(
        "characterize",
        route_after_synthesis_step,
        {"next": "generalize", "finish_with_error": "finish_with_error"},
    )
    .add_conditional_edges(
        "generalize",
        route_after_synthesis_step,
        {"next": "answer", "finish_with_error": "finish_with_error"},
    )
    .add_edge("answer", END)
    .add_edge("early_finish", END)
    .add_edge("finish_with_error", END)
    .compile(name="Dialect MAS")
)
