from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

AG1_STANCE = """
        Your stance:
        a is a camera.
        c is a camera.
        a is compact.
        a is light.
        c has long battery life.
        c is user-friendly.
        b is over budget.
        If a camera is compact and light, we should buy it.
        If something is over budget, we should not buy it.
        If something is compact and light, it is user-friendly.
        """

AG2_STANCE = """
        Your stance:
        b is a camera.
        a is out of stock.
        b has long battery life.
        b has high image quality.
        If a camera has high image quality and long battery life, we should buy it.
        If something is out of stock, we should not buy it.
        """

QUESTION = "What camera should we buy?"

INTERNAL_STATE_FIELDS = {
    "last_generated_argument",
    "current_argument",
    "active_agent",
    "debate_stage",
    "turn_count",
    "last_can_defeat",
    "last_generated_argument_appended",
    "ag1_main_argument",
    "ag2_main_argument",
    "ag1_pending",
    "ag2_pending",
    "history",
    "warrant_result",
    "generalization_result",
    "integration_result",
}


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


def _node_payload(node_name: str, update: dict[str, Any]) -> Any:
    if node_name == "update_learned_findings":
        return {k: _parse_json_text(v) for k, v in update.items() if v is not None}

    if node_name in {"ag1_main", "ag2_main"}:
        payload = _record_argument_payload(update.get("current_argument"))
        if payload is not None:
            if update.get("learned_findings"):
                return {
                    "argument": payload,
                    "learned_findings": update["learned_findings"],
                }
            return payload

    if node_name in {"ag2_attack_ag1", "ag1_counter_ag2", "ag1_attack_ag2", "ag2_counter_ag1"}:
        payload = _record_argument_payload(update.get("last_generated_argument"))
        if payload is not None:
            result = {"argument": payload}
            if update.get("learned_findings"):
                result["learned_findings"] = update["learned_findings"]
            return result
        if update.get("last_can_defeat") is False:
            if update.get("justified_argument"):
                return {
                    "can_defeat": "NO",
                    "justified_argument": _parse_json_text(update["justified_argument"]),
                    "justification_status": update.get("justification_status"),
                    "learned_findings": update.get("learned_findings"),
                }
            return {"can_defeat": "NO"}

    if node_name in {"extract_warrants", "generalize", "integrate"}:
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

    if node_name in {"early_finish", "finish_with_error"}:
        if update.get("justified_argument"):
            return {
                "justified_argument": _parse_json_text(update["justified_argument"]),
                "justification_status": update.get("justification_status"),
                "final_rebuttal": _parse_json_text(update.get("final_rebuttal")),
                "learned_findings": update.get("learned_findings"),
                "error": update.get("error"),
            }

        public_update = {k: v for k, v in update.items() if k not in INTERNAL_STATE_FIELDS}
        return {k: _parse_json_text(v) for k, v in public_update.items() if v is not None}

    return {k: _parse_json_text(v) for k, v in update.items() if v is not None}


def _print_node_output(node_name: str, payload: Any) -> None:
    print(f"[{node_name}]")
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    print()


def _load_input(path: str | None) -> dict[str, Any]:
    if not path:
        return {}

    input_path = Path(path)
    return json.loads(input_path.read_text(encoding="utf-8"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the debate graph locally and stream each node output.",
    )
    parser.add_argument("--input", help="Path to a JSON file containing graph input.")
    parser.add_argument("--question", default=QUESTION)
    parser.add_argument("--agent1-stance", default=AG1_STANCE)
    parser.add_argument("--agent2-stance", default=AG2_STANCE)
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

    print("[system]", flush=True)
    print(json.dumps({"status": "loading_graph"}, ensure_ascii=False, indent=2), flush=True)
    print(flush=True)

    from src.agent.graph import State, graph

    file_input = _load_input(args.input)
    cli_input = {
        "question": args.question,
        "agent1_stance": args.agent1_stance,
        "agent2_stance": args.agent2_stance,
        "max_turns": args.max_turns,
        "additional_context": json.loads(args.additional_context),
    }
    graph_input = State(**{**cli_input, **file_input})

    print("[system]", flush=True)
    print(json.dumps({"status": "starting_stream"}, ensure_ascii=False, indent=2), flush=True)
    print(flush=True)

    async for update in graph.astream(graph_input, stream_mode="updates"):
        for node_name, node_update in update.items():
            payload = _node_payload(node_name, node_update)
            _print_node_output(node_name, payload)


if __name__ == "__main__":
    asyncio.run(run())
