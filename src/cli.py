from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# python3 src/cli.py --scenario curry 

# プロジェクトのルートディレクトリを sys.path に追加
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"


def _load_config() -> dict:
    return json.loads((DATA_DIR / "config.json").read_text(encoding="utf-8"))


def _load_scenario(name: str) -> dict:
    path = DATA_DIR / "scenarios" / f"{name}.json"
    if not path.exists():
        available = [p.stem for p in (DATA_DIR / "scenarios").glob("*.json")]
        raise FileNotFoundError(f"Scenario '{name}' not found. Available: {available}")
    return json.loads(path.read_text(encoding="utf-8"))


_CONFIG = _load_config()
INTERNAL_STATE_FIELDS: set[str] = set(_CONFIG["internal_state_fields"])
DEFAULT_SCENARIO: str = _CONFIG["default_scenario"]


def _parse_json_text(value: Any) -> Any:
    if not isinstance(value, str):
        return value

    text = value.strip()
    if not text:
        return value

    if "```json" in text:
        start = text.find("```json") + len("```json")
        end = text.find("```", start)
        text = text[start:end].strip()
    elif text.startswith("```") and text.endswith("```"):
        text = text[3:-3].strip()

    if not text.startswith("{"):
        return value

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return value


def _record_argument_payload(record: Any) -> Any:
    if record is None:
        return None
    if hasattr(record, "argument"):
        return _parse_json_text(record.argument)
    if isinstance(record, dict) and "argument" in record:
        return _parse_json_text(record["argument"])
    return record


def _record_metadata(record: Any) -> dict[str, Any]:
    if record is None:
        return {}
    result: dict[str, Any] = {}
    for key in ("id", "type", "agent", "attack", "target_id", "target_field", "target_statement", "status"):
        value = getattr(record, key, None)
        if value is not None:
            result[key] = value
    if isinstance(record, dict):
        for key in ("id", "type", "agent", "attack", "target_id", "target_field", "target_statement", "status"):
            value = record.get(key)
            if value is not None:
                result[key] = value
    return result


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return _jsonable(value.model_dump())
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    return _parse_json_text(value)


def _status_payload(update: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in (
        "current_thread_status",
        "ag1_thread_status",
        "ag2_thread_status",
        "current_proponent",
        "current_opponent",
        "active_agent",
        "debate_stage",
        "debate_round",
    ):
        if update.get(key) is not None:
            result[key] = update[key]
    return result


def _node_payload(node_name: str, update: dict[str, Any]) -> Any:
    if update is None:
        return None

    if not update:
        return None

    if node_name == "update_learned_findings":
        return _jsonable({k: v for k, v in update.items() if v is not None})

    if node_name in {"ag1_main", "ag2_main", "can_generate_main"}:
        payload = _record_argument_payload(update.get("current_argument"))
        if payload is not None:
            result = {"argument": payload}
            metadata = _record_metadata(update.get("current_argument"))
            if metadata:
                result["metadata"] = metadata
            if update.get("main_argument_available") is not None:
                result["main_argument_available"] = update["main_argument_available"]
            if update.get("main_argument_unavailable_reason"):
                result["main_argument_unavailable_reason"] = update["main_argument_unavailable_reason"]
            if update.get("learned_findings"):
                result["learned_findings"] = update["learned_findings"]
            return result

    if node_name in {
        "ag2_attack_ag1",
        "ag1_counter_ag2",
        "ag1_attack_ag2",
        "ag2_counter_ag1",
        "o_defeat_a",
        "validate_b_defeats_a",
        "p_counter_b",
        "validate_c_defeats_b",
        "validate_b_defeats_c",
    }:
        record = update.get("last_generated_argument")
        payload = _record_argument_payload(record)
        if payload is None:
            for key in ("b_argument", "c_argument", "d_argument"):
                record = update.get(key)
                payload = _record_argument_payload(record)
                if payload is not None:
                    break
        if payload is not None:
            record = update.get("last_generated_argument")
            if record is None:
                for key in ("b_argument", "c_argument", "d_argument"):
                    record = update.get(key)
                    if record is not None:
                        break
            result = {"argument": payload}
            metadata = _record_metadata(record)
            if metadata:
                result["metadata"] = metadata
            if update.get("current_thread_status"):
                result["thread_status"] = update["current_thread_status"]
            if update.get("learned_findings"):
                result["learned_findings"] = update["learned_findings"]
            if update.get("defeat_relations"):
                result["defeat_relations"] = _jsonable(update["defeat_relations"])
            return result
        if update.get("current_thread_status"):
            return _status_payload(update)
        if update.get("last_can_defeat") is False:
            if update.get("justified_argument"):
                return {
                    "can_defeat": "NO",
                    "justified_argument": _parse_json_text(update["justified_argument"]),
                    "justification_status": update.get("justification_status"),
                    "learned_findings": update.get("learned_findings"),
                }
            return {"can_defeat": "NO"}
        validation_payload = _status_payload(update)
        for key in (
            "last_can_defeat",
            "b_defeats_a",
            "c_defeats_b",
            "b_defeats_c",
            "c_strictly_defeats_b",
        ):
            if update.get(key) is not None:
                validation_payload[key] = update[key]
        if validation_payload:
            return validation_payload
        return None

    if node_name in {"extract_warrants", "generalize", "integrate", "add_integrated_rule"}:
        if node_name == "add_integrated_rule":
            return {
                "integrated_rules": _jsonable(update.get("integrated_rules")),
                "debate_round": update.get("debate_round"),
            }
        for key in ("warrant_result", "generalization_result", "integration_result"):
            if key in update and update[key] is not None:
                payload = _parse_json_text(update[key])
                if node_name == "integrate":
                    result = {"integration_result": payload}
                    if update.get("integrated_rule") is not None:
                        result["integrated_rule"] = update["integrated_rule"]
                    if update.get("learned_findings"):
                        result["learned_findings"] = update["learned_findings"]
                    return result
                if update.get("learned_findings"):
                    return {
                        "result": payload,
                        "learned_findings": update["learned_findings"],
                    }
                return payload

    if node_name in {"early_finish", "finish", "finish_with_error"}:
        return {
            "justified_argument": _parse_json_text(update.get("justified_argument")),
            "justification_status": update.get("justification_status"),
            "final_rebuttal": _parse_json_text(update.get("final_rebuttal")),
            "dialogue_history": _jsonable(update.get("dialogue_history")),
            "ag1_thread_status": update.get("ag1_thread_status"),
            "ag2_thread_status": update.get("ag2_thread_status"),
            "integrated_rules": update.get("integrated_rules"),
            "learned_findings": update.get("learned_findings"),
            "error": update.get("error"),
        }

    public_update = {k: v for k, v in update.items() if k not in INTERNAL_STATE_FIELDS}
    return _jsonable({k: v for k, v in public_update.items() if v is not None})


def _print_node_output(node_name: str, payload: Any) -> None:
    if payload is None:
        return
    print(f"[{node_name}]")
    print(json.dumps(_jsonable(payload), ensure_ascii=False, indent=2, default=str))
    print()


def _load_input(path: str | None) -> dict[str, Any]:
    if not path:
        return {}

    input_path = Path(path)
    return json.loads(input_path.read_text(encoding="utf-8"))


def _save_log(args: argparse.Namespace, graph_input: Any, final_state: dict[str, Any]) -> None:
    logs_dir = Path(__file__).resolve().parents[1] / "logs"
    logs_dir.mkdir(exist_ok=True)

    log_entry = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "question": graph_input.question,
        "agent1_stance": graph_input.agent1_stance,
        "agent2_stance": graph_input.agent2_stance,
        "dialogue_history": _jsonable(final_state.get("dialogue_history", [])),
        "justified_argument": _parse_json_text(final_state.get("justified_argument")),
        "justification_status": final_state.get("justification_status"),
        "defeat_relations": _jsonable(final_state.get("defeat_relations", [])),
        "ag1_thread_status": final_state.get("ag1_thread_status"),
        "ag2_thread_status": final_state.get("ag2_thread_status"),
        "integrated_rules": final_state.get("integrated_rules", []),
        "learned_findings": final_state.get("learned_findings", []),
        "error": final_state.get("error"),
    }

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = logs_dir / f"{timestamp}.json"
    log_path.write_text(json.dumps(log_entry, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[system] log saved → {log_path}", flush=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the debate graph locally and stream each node output.",
    )
    parser.add_argument("scenario", nargs="?", default=DEFAULT_SCENARIO,
                        help=f"Scenario name under data/scenarios/ (default: {DEFAULT_SCENARIO})")
    parser.add_argument("--input", help="Path to a JSON file containing graph input.")
    parser.add_argument("--question", default=None, help="Override scenario question.")
    parser.add_argument("--agent1-stance", default=None, help="Override AG1 stance.")
    parser.add_argument("--agent2-stance", default=None, help="Override AG2 stance.")
    parser.add_argument("--max-turns", type=int, default=5)
    parser.add_argument(
        "--additional-context",
        default="{}",
        help="JSON string for additional_context.",
    )
    return parser


async def run() -> None:
    parser = build_parser()
    args = parser.parse_args()

    scenario = _load_scenario(args.scenario)

    print("[system]", flush=True)
    print(json.dumps({"status": "loading_graph"}, ensure_ascii=False, indent=2), flush=True)
    print(flush=True)

    from src.agent.workflow import State, graph

    file_input = _load_input(args.input)
    cli_input = {
        "question": args.question or scenario["question"],
        "agent1_stance": args.agent1_stance or scenario["agent1_stance"],
        "agent2_stance": args.agent2_stance or scenario["agent2_stance"],
        "max_turns": args.max_turns,
        "additional_context": json.loads(args.additional_context),
    }
    graph_input = State(**{**cli_input, **file_input})

    print("[system]", flush=True)
    print(json.dumps({"status": "starting_stream"}, ensure_ascii=False, indent=2), flush=True)
    print(flush=True)

    final_state: dict[str, Any] = {}

    async for update in graph.astream(graph_input, stream_mode="updates"):
        for node_name, node_update in update.items():
            payload = _node_payload(node_name, node_update)
            if node_name not in {"finish", "finish_with_error"}:
                _print_node_output(node_name, payload)
            if node_name in {"finish", "finish_with_error"}:
                final_state = node_update if isinstance(node_update, dict) else {}

    _save_log(args, graph_input, final_state)


if __name__ == "__main__":
    asyncio.run(run())
