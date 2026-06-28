"""Shared runners for schema-based and no-schema dialogue experiments."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, cast

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult

ROOT = Path(__file__).resolve().parents[2]
DATASETS_DIR = ROOT / "datasets"
LOGS_DIR = ROOT / "logs"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

Method = Literal["schema", "no_schema", "free_debate", "mad"]

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
    keys = (
        "id",
        "round",
        "type",
        "agent",
        "attack",
        "target_id",
        "target_field",
        "target_statement",
        "status",
    )
    for key in keys:
        value = getattr(record, key, None)
        if value is not None:
            result[key] = value
    if isinstance(record, dict):
        for key in keys:
            value = record.get(key)
            if value is not None:
                result[key] = value
    return result


def _record_id(record: Any) -> str | None:
    if record is None:
        return None
    value = getattr(record, "id", None)
    if isinstance(value, str):
        return value
    if isinstance(record, dict) and isinstance(record.get("id"), str):
        return cast(str, record["id"])
    return None


def _format_argument_for_terminal(argument: Any) -> str:
    """Argument payload を JSON schema の形のまま端末表示する."""
    if isinstance(argument, str):
        text = argument.strip()
        return text if text else "(no argument)"

    if not isinstance(argument, dict):
        return "(no argument)"

    return json.dumps(argument, ensure_ascii=False, indent=2)


def _print_argument_turn(record: Any, seen_ids: set[str]) -> None:
    """生成された発話を一度だけ端末へ出す."""
    record_id = _record_id(record)
    if record_id is not None:
        if record_id in seen_ids:
            return
        seen_ids.add(record_id)

    payload = _record_argument_payload(record)
    if payload is None:
        return

    metadata = _record_metadata(record)
    agent = metadata.get("agent", "?")
    argument_type = metadata.get("type", "?")
    round_no = metadata.get("round")
    header_parts = ["[turn]"]
    if round_no is not None:
        header_parts.append(f"round {round_no}")
    header_parts.append(str(agent))
    header_parts.append(str(argument_type))
    if metadata.get("attack"):
        header_parts.append(f"({metadata['attack']} on {metadata.get('target_field', '?')})")
    print(" ".join(header_parts), flush=True)  # noqa: T201
    if record_id is not None:
        print(f"  id: {record_id}", flush=True)  # noqa: T201
    if metadata.get("target_id"):
        print(f"  target: {metadata['target_id']}", flush=True)  # noqa: T201
    if metadata.get("target_statement"):
        print(f"  target_statement: {metadata['target_statement']}", flush=True)  # noqa: T201
    print(_format_argument_for_terminal(payload), flush=True)  # noqa: T201
    print("", flush=True)  # noqa: T201


def _print_stream_update(
    node_name: str, update: dict[str, Any], seen_ids: set[str]
) -> None:
    """LangGraph の node update から発話を拾って端末へ出す."""
    if node_name in {"can_generate_main", "o_defeat_a", "p_counter_b"}:
        record = update.get("current_argument") or update.get("last_generated_argument")
        _print_argument_turn(record, seen_ids)
        return
    if node_name.startswith("validate_"):
        _print_argument_turn(update.get("last_generated_argument"), seen_ids)


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
    topic_data: dict[str, Any],
    elapsed: float,
    usage: dict[str, Any],
) -> dict[str, Any]:
    return {
        "method": method,
        "question": topic_data["question"],
        "agent1_stance": topic_data["agent1_stance"],
        "agent2_stance": topic_data["agent2_stance"],
        "metrics": {
            "elapsed_seconds": round(elapsed, 3),
            **usage,
        },
    }


def _speech_log(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """対話履歴から、各エージェントの発話（agent/argument）だけを抜き出す."""
    return [
        {"agent": record.get("agent"), "argument": record.get("argument")}
        for record in history
    ]


async def _run_topic_once(
    method: Method,
    topic_file: str | Path,
    *,
    max_turns: int = 3,
    max_main_argument_attempts: int | None = None,
    output_root: Path = LOGS_DIR,
    run_index: int | None = None,
) -> Path:
    """schema / no_schema 共通の実行ロジック.

    両条件とも同じ LangGraph（討論プロトコル・プロンプト）を使い、
    `State.output_mode` だけを切り替える（no_schema は Argument 本体の rules/Conc/Ass
    スキーマを取り除き、自由記述の natural language として出力させる）。
    """
    from src.agent.workflow import State, graph

    topic_path, topic_data = load_topic(topic_file)
    tracker = TokenUsageTracker()
    state_kwargs: dict[str, Any] = {
        "question": topic_data["question"],
        "agent1_stance": topic_data["agent1_stance"],
        "agent2_stance": topic_data["agent2_stance"],
        "max_turns": max_turns,
        "additional_context": cast(dict[str, Any], topic_data.get("additional_context", {})),
        "output_mode": method,
    }
    if max_main_argument_attempts is not None:
        state_kwargs["max_main_argument_attempts"] = max_main_argument_attempts
    graph_input = State(**state_kwargs)

    start = time.perf_counter()
    result: dict[str, Any] = dict(graph_input.__dict__)
    seen_argument_ids: set[str] = set()
    async for event in graph.astream(
        graph_input,  # type: ignore[arg-type]
        config={"callbacks": [tracker]},
        stream_mode="updates",
    ):
        if not isinstance(event, dict):
            continue
        for node_name, update in event.items():
            if not isinstance(update, dict):
                continue
            _print_stream_update(node_name, update, seen_argument_ids)
            result.update(update)
    elapsed = time.perf_counter() - start
    final_state = _jsonable(result)

    log = base_log(
        method=method,
        topic_data=topic_data,
        elapsed=elapsed,
        usage=tracker.usage(),
    )
    log["dialogue_history"] = _speech_log(final_state.get("dialogue_history", []))
    log["final_answer"] = final_state.get("final_answer")
    error = final_state.get("error")
    if error is not None:
        log["error"] = error
    path = save_log(log, output_path(method, topic_path, output_root, run_index))
    print(f"[system] log saved -> {path}", flush=True)
    return path


async def run_schema_topic_once(
    topic_file: str | Path,
    *,
    max_turns: int = 3,
    max_main_argument_attempts: int | None = None,
    output_root: Path = LOGS_DIR,
    run_index: int | None = None,
) -> Path:
    return await _run_topic_once(
        "schema",
        topic_file,
        max_turns=max_turns,
        max_main_argument_attempts=max_main_argument_attempts,
        output_root=output_root,
        run_index=run_index,
    )


async def run_no_schema_topic_once(
    topic_file: str | Path,
    *,
    max_turns: int = 3,
    max_main_argument_attempts: int | None = None,
    output_root: Path = LOGS_DIR,
    run_index: int | None = None,
) -> Path:
    return await _run_topic_once(
        "no_schema",
        topic_file,
        max_turns=max_turns,
        max_main_argument_attempts=max_main_argument_attempts,
        output_root=output_root,
        run_index=run_index,
    )


async def run_free_debate_topic_once(
    topic_file: str | Path,
    *,
    max_turns: int = 3,
    output_root: Path = LOGS_DIR,
    run_index: int | None = None,
) -> Path:
    """弁証法プロトコルを使わない自由討議ベースラインを1トピック実行する.

    schema/no_schema と異なるグラフ・State（free_debate.FreeDebateState）を使うため、
    `_run_topic_once` を流用せず専用の実行ロジックを持つ。main argument 再試行という
    概念が無いため `max_main_argument_attempts` は存在しない。
    """
    from src.agent.free_debate import FreeDebateState, graph_free_debate

    topic_path, topic_data = load_topic(topic_file)
    tracker = TokenUsageTracker()
    graph_input = FreeDebateState(
        question=topic_data["question"],
        agent1_stance=topic_data["agent1_stance"],
        agent2_stance=topic_data["agent2_stance"],
        max_turns=max_turns,
    )

    start = time.perf_counter()
    result: dict[str, Any] = dict(graph_input.__dict__)
    async for event in graph_free_debate.astream(
        graph_input,  # type: ignore[arg-type]
        config={"callbacks": [tracker]},
        stream_mode="updates",
    ):
        if not isinstance(event, dict):
            continue
        for node_name, update in event.items():
            if not isinstance(update, dict):
                continue
            if node_name in ("ag1_turn", "ag2_turn") and update.get("dialogue_history"):
                record = update["dialogue_history"][-1]
                print(f"[turn] round {record['round']} {record['agent']}", flush=True)  # noqa: T201
                print(record["argument"], flush=True)  # noqa: T201
                print("", flush=True)  # noqa: T201
            result.update(update)
    elapsed = time.perf_counter() - start

    log = base_log(
        method="free_debate",
        topic_data=topic_data,
        elapsed=elapsed,
        usage=tracker.usage(),
    )
    log["dialogue_history"] = result.get("dialogue_history", [])
    log["final_answer"] = result.get("final_answer")
    path = save_log(log, output_path("free_debate", topic_path, output_root, run_index))
    print(f"[system] log saved -> {path}", flush=True)
    return path


async def run_category(
    method: Method,
    category: str | Path,
    *,
    runs: int = 1,
    max_turns: int = 3,
    max_main_argument_attempts: int | None = None,
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
                            max_main_argument_attempts=max_main_argument_attempts,
                            output_root=output_root,
                            run_index=index if runs > 1 else None,
                        )
                    )
                else:
                    saved.append(
                        await run_no_schema_topic_once(
                            topic_file,
                            max_turns=max_turns,
                            max_main_argument_attempts=max_main_argument_attempts,
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
    parser.add_argument("--max-turns", type=int, default=3, help="Maximum debate rounds (used by both schema and no-schema).")
    parser.add_argument("--max-main-argument-attempts", type=int, default=None, help="Per-round main argument retry cap (defaults to State's MAX_MAIN_ARGUMENT_ATTEMPTS env default).")
    parser.add_argument("--output-root", type=Path, default=LOGS_DIR, help="Root directory for logs.")
    return parser


def category_parser(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("category", help="Category name under datasets/ or a category directory path.")
    parser.add_argument("--runs", type=int, default=1, help="Number of runs per topic.")
    parser.add_argument("--max-turns", type=int, default=3, help="Maximum debate rounds (used by both schema and no-schema).")
    parser.add_argument("--max-main-argument-attempts", type=int, default=None, help="Per-round main argument retry cap (defaults to State's MAX_MAIN_ARGUMENT_ATTEMPTS env default).")
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
                    max_main_argument_attempts=args.max_main_argument_attempts,
                    output_root=args.output_root,
                    run_index=index if args.runs > 1 else None,
                )
            )
        else:
            saved.append(
                await run_no_schema_topic_once(
                    args.json_file,
                    max_turns=args.max_turns,
                    max_main_argument_attempts=args.max_main_argument_attempts,
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
            max_main_argument_attempts=args.max_main_argument_attempts,
            output_root=args.output_root,
            continue_on_error=not args.fail_fast,
        )
    )
