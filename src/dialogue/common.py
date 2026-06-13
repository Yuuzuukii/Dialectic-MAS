"""Shared runners for schema-based and no-schema dialogue experiments."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, cast

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult
from langchain_core.runnables import RunnableConfig

ROOT = Path(__file__).resolve().parents[2]
DATASETS_DIR = ROOT / "datasets"
LOGS_DIR = ROOT / "logs"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

Method = Literal["schema", "no_schema"]

_PRICE_INPUT_PER_M = 0.25
_PRICE_CACHED_PER_M = 0.025
_PRICE_OUTPUT_PER_M = 2.00


class TokenUsageTracker(BaseCallbackHandler):
    """Track OpenAI token usage and estimate run cost."""

    def __init__(self) -> None:
        self.prompt_tokens = 0
        self.cached_tokens = 0
        self.completion_tokens = 0
        self.total_tokens = 0

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        token_usage = (response.llm_output or {}).get("token_usage", {})
        self.prompt_tokens += token_usage.get("prompt_tokens", 0)
        self.completion_tokens += token_usage.get("completion_tokens", 0)
        self.total_tokens += token_usage.get("total_tokens", 0)
        details = token_usage.get("prompt_tokens_details") or {}
        self.cached_tokens += details.get("cached_tokens", 0)

    def usage(self) -> dict[str, Any]:
        non_cached = self.prompt_tokens - self.cached_tokens
        cost = (
            non_cached * _PRICE_INPUT_PER_M
            + self.cached_tokens * _PRICE_CACHED_PER_M
            + self.completion_tokens * _PRICE_OUTPUT_PER_M
        ) / 1_000_000
        return {
            "prompt_tokens": self.prompt_tokens,
            "cached_tokens": self.cached_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "total_cost_usd": round(cost, 6),
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


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return _jsonable(value.model_dump())
    if hasattr(value, "__dataclass_fields__"):
        return _jsonable(value.__dict__)
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    return _parse_json_text(value)


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


def _node_payload(node_name: str, update: dict[str, Any]) -> Any:
    """Return compact public payloads for streamed schema graph updates."""
    if not update:
        return None
    if node_name in {"can_generate_main", "o_defeat_a", "p_counter_b"}:
        record = update.get("current_argument") or update.get("last_generated_argument")
        payload = _record_argument_payload(record)
        if payload is None:
            return None
        result = {"argument": payload}
        metadata = _record_metadata(record)
        if metadata:
            result["metadata"] = metadata
        return result
    if node_name.startswith("validate_"):
        record = update.get("last_generated_argument")
        payload = _record_argument_payload(record)
        if payload is None:
            return {"thread_status": update.get("current_thread_status")}
        result = {"argument": payload}
        metadata = _record_metadata(record)
        if metadata:
            result["metadata"] = metadata
        if update.get("current_thread_status"):
            result["thread_status"] = update["current_thread_status"]
        return result
    if node_name in {"finish", "finish_with_error"}:
        return _jsonable(update)
    return _jsonable({k: v for k, v in update.items() if v is not None})


def load_topic(path: str | Path) -> tuple[Path, dict[str, Any]]:
    topic_path = Path(path)
    if not topic_path.is_absolute():
        topic_path = ROOT / topic_path
    if not topic_path.exists():
        raise FileNotFoundError(f"Topic JSON not found: {topic_path}")
    data = cast(dict[str, Any], json.loads(topic_path.read_text(encoding="utf-8")))
    for key in ("question", "agent1_stance", "agent2_stance"):
        if key not in data:
            raise ValueError(f"{topic_path} is missing required key: {key}")
    return topic_path, data


def resolve_category(category: str | Path, datasets_dir: Path = DATASETS_DIR) -> Path:
    raw = Path(category)
    path = raw if raw.is_absolute() else datasets_dir / raw
    if not path.is_dir():
        raise FileNotFoundError(f"Category directory not found: {path}")
    return path


def category_topic_files(category: str | Path, datasets_dir: Path = DATASETS_DIR) -> list[Path]:
    category_dir = resolve_category(category, datasets_dir)
    return sorted(p for p in category_dir.glob("*.json") if p.is_file())


def topic_identity(topic_path: Path) -> tuple[str, str]:
    return topic_path.parent.name, topic_path.stem


def output_path(method: Method, topic_path: Path, output_root: Path, run_index: int | None) -> Path:
    category, topic = topic_identity(topic_path)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    prefix = f"{run_index:02d}_" if run_index is not None else ""
    return output_root / category / topic / f"{prefix}{method}_{timestamp}.json"


def save_log(log: dict[str, Any], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(log, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return path


def base_log(
    *,
    method: Method,
    topic_path: Path,
    topic_data: dict[str, Any],
    elapsed: float,
    usage: dict[str, Any],
) -> dict[str, Any]:
    category, topic = topic_identity(topic_path)
    return {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "method": method,
        "category": category,
        "topic": topic,
        "source_path": str(topic_path),
        "question": topic_data["question"],
        "agent1_stance": topic_data["agent1_stance"],
        "agent2_stance": topic_data["agent2_stance"],
        "metrics": {
            "elapsed_seconds": round(elapsed, 3),
            **usage,
        },
    }


async def run_schema_topic_once(
    topic_file: str | Path,
    *,
    max_turns: int = 3,
    output_root: Path = LOGS_DIR,
    run_index: int | None = None,
) -> Path:
    from src.agent.workflow import State, graph

    topic_path, topic_data = load_topic(topic_file)
    tracker = TokenUsageTracker()
    graph_input = State(
        question=topic_data["question"],
        agent1_stance=topic_data["agent1_stance"],
        agent2_stance=topic_data["agent2_stance"],
        max_turns=max_turns,
        additional_context=cast(dict[str, Any], topic_data.get("additional_context", {})),
    )

    start = time.perf_counter()
    result = await graph.ainvoke(
        graph_input,  # type: ignore[arg-type]
        config={"callbacks": [tracker]},
    )
    elapsed = time.perf_counter() - start
    final_state = _jsonable(result)

    log = base_log(
        method="schema",
        topic_path=topic_path,
        topic_data=topic_data,
        elapsed=elapsed,
        usage=tracker.usage(),
    )
    log.update(
        {
            "dialogue_history": final_state.get("dialogue_history", []),
            "integrated_rules": final_state.get("integrated_rules", []),
            "justified_argument": final_state.get("justified_argument"),
            "justification_status": final_state.get("justification_status"),
            "consensus_reached": final_state.get("consensus_reached"),
            "final_answer": final_state.get("final_answer"),
            "ag1_thread_status": final_state.get("ag1_thread_status"),
            "ag2_thread_status": final_state.get("ag2_thread_status"),
            "error": final_state.get("error"),
        }
    )
    path = save_log(log, output_path("schema", topic_path, output_root, run_index))
    print(f"[system] log saved -> {path}", flush=True)
    return path


def _free_text_record(
    *,
    idx: int,
    rtype: str,
    agent: str,
    argument: str,
    target_id: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    return {
        "id": f"no-schema-{idx}",
        "round": 1,
        "type": rtype,
        "argument": argument,
        "support": [],
        "agent": agent,
        "target_id": target_id,
        "attack": None,
        "target_field": None,
        "target_statement": None,
        "status": status,
    }


async def run_no_schema_topic_once(
    topic_file: str | Path,
    *,
    output_root: Path = LOGS_DIR,
    run_index: int | None = None,
) -> Path:
    from langchain_core.messages import HumanMessage

    from src.agent.llm import chat_text

    topic_path, topic_data = load_topic(topic_file)
    model = os.getenv("MODEL", "gpt-5-mini")
    tracker = TokenUsageTracker()
    config: RunnableConfig = {"callbacks": [tracker]}
    q = topic_data["question"]
    s1 = topic_data["agent1_stance"]
    s2 = topic_data["agent2_stance"]

    async def step(label: str, prompt: str) -> str:
        print(f"[{label}]", flush=True)
        result = await chat_text(
            [HumanMessage(content=prompt)], model=model, config=config
        )
        print(result, flush=True)
        print(flush=True)
        return result

    start = time.perf_counter()
    ag1_claim = await step("AG1 main claim", f"""\
You are AG1 in a dialogue. Answer the question from your stance.

Question: {q}
Your stance: {s1}

State your argument in 2-3 sentences.""")
    ag2_counter = await step("AG2 counter to AG1", f"""\
You are AG2 in a dialogue. Counter the argument below.

Question: {q}
AG1's argument: {ag1_claim}
Your stance: {s2}

State your counterargument in 2-3 sentences.""")
    ag2_claim = await step("AG2 main claim", f"""\
You are AG2 in a dialogue. Answer the question from your stance.

Question: {q}
Your stance: {s2}

State your argument in 2-3 sentences.""")
    ag1_counter = await step("AG1 counter to AG2", f"""\
You are AG1 in a dialogue. Counter the argument below.

Question: {q}
AG2's argument: {ag2_claim}
Your stance: {s1}

State your counterargument in 2-3 sentences.""")
    agreement_core = await step("Agreement core", f"""\
Two agents have debated the following question.

Question: {q}

AG1 argued: {ag1_claim}
AG2 argued: {ag2_claim}
AG1 countered AG2 with: {ag1_counter}
AG2 countered AG1 with: {ag2_counter}

Identify the shared values or criteria both agents implicitly agree on.
State the agreement core as 1-2 abstract principles.""")
    ag1_new_claim = await step("AG1 new claim after agreement", f"""\
You are AG1. Based on the agreement core below, revise your argument for the question.

Question: {q}
Your original stance: {s1}
Agreement core: {agreement_core}

State your updated argument in 2-3 sentences.""")
    elapsed = time.perf_counter() - start

    dialogue_history = [
        _free_text_record(idx=1, rtype="main", agent="AG1", argument=ag1_claim),
        _free_text_record(idx=2, rtype="defeat", agent="AG2", argument=ag2_counter, target_id="no-schema-1"),
        _free_text_record(idx=3, rtype="main", agent="AG2", argument=ag2_claim),
        _free_text_record(idx=4, rtype="counter", agent="AG1", argument=ag1_counter, target_id="no-schema-3"),
        _free_text_record(idx=5, rtype="synthesis", agent="system", argument=agreement_core),
        _free_text_record(idx=6, rtype="main", agent="AG1", argument=ag1_new_claim, status="justified"),
    ]

    log = base_log(
        method="no_schema",
        topic_path=topic_path,
        topic_data=topic_data,
        elapsed=elapsed,
        usage=tracker.usage(),
    )
    log.update(
        {
            "dialogue_history": dialogue_history,
            "integrated_rules": [agreement_core],
            "justified_argument": ag1_new_claim,
            "justification_status": "no_schema",
            "consensus_reached": None,
            "final_answer": ag1_new_claim,
            "ag1_thread_status": None,
            "ag2_thread_status": None,
            "error": None,
        }
    )
    path = save_log(log, output_path("no_schema", topic_path, output_root, run_index))
    print(f"[system] log saved -> {path}", flush=True)
    return path


async def run_category(
    method: Method,
    category: str | Path,
    *,
    runs: int = 1,
    max_turns: int = 3,
    output_root: Path = LOGS_DIR,
    continue_on_error: bool = True,
) -> list[Path]:
    files = category_topic_files(category)
    if not files:
        raise FileNotFoundError(f"No topic JSON files found in category: {category}")
    saved: list[Path] = []
    for topic_file in files:
        print(f"=== [{method}][{topic_file.parent.name}] {topic_file.stem} ===", flush=True)
        for index in range(1, runs + 1):
            try:
                if method == "schema":
                    saved.append(
                        await run_schema_topic_once(
                            topic_file,
                            max_turns=max_turns,
                            output_root=output_root,
                            run_index=index if runs > 1 else None,
                        )
                    )
                else:
                    saved.append(
                        await run_no_schema_topic_once(
                            topic_file,
                            output_root=output_root,
                            run_index=index if runs > 1 else None,
                        )
                    )
            except Exception as exc:
                print(f"[error] {topic_file}: {exc}", file=sys.stderr, flush=True)
                if not continue_on_error:
                    raise
    return saved


def topic_parser(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("json_file", help="Path to a topic JSON file.")
    parser.add_argument("--runs", type=int, default=1, help="Number of runs for this topic.")
    parser.add_argument("--max-turns", type=int, default=3, help="Schema method max turns; ignored by no-schema.")
    parser.add_argument("--output-root", type=Path, default=LOGS_DIR, help="Root directory for logs.")
    return parser


def category_parser(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("category", help="Category name under datasets/ or a category directory path.")
    parser.add_argument("--runs", type=int, default=1, help="Number of runs per topic.")
    parser.add_argument("--max-turns", type=int, default=3, help="Schema method max turns; ignored by no-schema.")
    parser.add_argument("--output-root", type=Path, default=LOGS_DIR, help="Root directory for logs.")
    parser.add_argument("--fail-fast", action="store_true", help="Stop on the first topic failure.")
    return parser


async def run_topic_repeated(method: Method, args: argparse.Namespace) -> list[Path]:
    saved: list[Path] = []
    for index in range(1, args.runs + 1):
        if method == "schema":
            saved.append(
                await run_schema_topic_once(
                    args.json_file,
                    max_turns=args.max_turns,
                    output_root=args.output_root,
                    run_index=index if args.runs > 1 else None,
                )
            )
        else:
            saved.append(
                await run_no_schema_topic_once(
                    args.json_file,
                    output_root=args.output_root,
                    run_index=index if args.runs > 1 else None,
                )
            )
    return saved


def main_topic(method: Method, description: str) -> None:
    args = topic_parser(description).parse_args()
    asyncio.run(run_topic_repeated(method, args))


def main_category(method: Method, description: str) -> None:
    args = category_parser(description).parse_args()
    asyncio.run(
        run_category(
            method,
            args.category,
            runs=args.runs,
            max_turns=args.max_turns,
            output_root=args.output_root,
            continue_on_error=not args.fail_fast,
        )
    )
