"""
Schema-free dialectical dialogue — baseline for comparison with Dialect-MAS.

Flow:
  1. AG1 main claim
  2. AG2 counter to AG1
  3. AG2 main claim
  4. AG1 counter to AG2
  5. Agreement core generation
  6. AG1 new claim (based on agreement core)

Usage:
    python src/cli_no_schema.py
    python src/cli_no_schema.py --question "..." --agent1-stance "..." --agent2-stance "..."
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from langchain_core.runnables import RunnableConfig

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.agent.llm import call_llm
from src.cli import DEFAULT_SCENARIO, _TokenUsageTracker, _load_scenario

MODEL = "gpt-5-mini"


async def step(label: str, prompt: str, config: RunnableConfig | None = None) -> str:
    print(f"[{label}]")
    result = await call_llm(prompt, MODEL, config=config)
    print(result)
    print()
    return result


async def run() -> None:
    parser = argparse.ArgumentParser(description="Schema-free dialectical dialogue.")
    parser.add_argument("scenario", nargs="?", default=DEFAULT_SCENARIO,
                        help=f"Scenario name under data/scenarios/ (default: {DEFAULT_SCENARIO})")
    parser.add_argument("--question", default=None, help="Override scenario question.")
    parser.add_argument("--agent1-stance", default=None, help="Override AG1 stance.")
    parser.add_argument("--agent2-stance", default=None, help="Override AG2 stance.")
    args = parser.parse_args()

    scenario = _load_scenario(args.scenario)
    q = args.question or scenario["question"]
    s1 = args.agent1_stance or scenario["agent1_stance"]
    s2 = args.agent2_stance or scenario["agent2_stance"]

    # cli.py と同様にトークン使用量を計測（同一トラッカ＝同一の単価で原価換算）。
    tracker = _TokenUsageTracker()
    run_config: RunnableConfig = {"callbacks": [tracker]}

    async def tracked(label: str, prompt: str) -> str:
        return await step(label, prompt, run_config)

    start = time.perf_counter()

    # 1. AG1 main claim
    ag1_claim = await tracked("AG1 main claim", f"""\
You are AG1 in a dialogue. Answer the question from your stance.

Question: {q}
Your stance: {s1}

State your argument in 2-3 sentences.""")

    # 2. AG2 counter to AG1
    ag2_counter = await tracked("AG2 counter to AG1", f"""\
You are AG2 in a dialogue. Counter the argument below.

Question: {q}
AG1's argument: {ag1_claim}
Your stance: {s2}

State your counterargument in 2-3 sentences.""")

    # 3. AG2 main claim
    ag2_claim = await tracked("AG2 main claim", f"""\
You are AG2 in a dialogue. Answer the question from your stance.

Question: {q}
Your stance: {s2}

State your argument in 2-3 sentences.""")

    # 4. AG1 counter to AG2
    ag1_counter = await tracked("AG1 counter to AG2", f"""\
You are AG1 in a dialogue. Counter the argument below.

Question: {q}
AG2's argument: {ag2_claim}
Your stance: {s1}

State your counterargument in 2-3 sentences.""")

    # 5. Agreement core
    agreement_core = await tracked("Agreement core", f"""\
Two agents have debated the following question.

Question: {q}

AG1 argued: {ag1_claim}
AG2 argued: {ag2_claim}
AG1 countered AG2 with: {ag1_counter}
AG2 countered AG1 with: {ag2_counter}

Identify the shared values or criteria both agents implicitly agree on.
State the agreement core as 1-2 abstract principles.""")

    # 6. AG1 new claim
    ag1_new_claim = await tracked("AG1 new claim (after agreement)", f"""\
You are AG1. Based on the agreement core below, revise your argument for the question.

Question: {q}
Your original stance: {s1}
Agreement core: {agreement_core}

State your updated argument in 2-3 sentences.""")

    elapsed = time.perf_counter() - start

    _save_log(args, {
        "ag1_claim": ag1_claim,
        "ag2_counter": ag2_counter,
        "ag2_claim": ag2_claim,
        "ag1_counter": ag1_counter,
        "agreement_core": agreement_core,
        "ag1_new_claim": ag1_new_claim,
    }, elapsed, tracker.usage())


def _save_log(
    args: argparse.Namespace,
    dialogue: dict[str, str],
    elapsed: float,
    usage: dict[str, Any] | None = None,
) -> None:
    logs_dir = ROOT / "eval" / "logs-v1-no-schema"
    logs_dir.mkdir(parents=True, exist_ok=True)

    log_entry = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "mode": "no-schema",
        "question": args.question,
        "agent1_stance": args.agent1_stance,
        "agent2_stance": args.agent2_stance,
        "dialogue": dialogue,
        "metrics": {
            "elapsed_seconds": round(elapsed, 3),
            **(usage or {}),
        },
    }

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = logs_dir / f"no-schema_{timestamp}.json"
    log_path.write_text(json.dumps(log_entry, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[system] log saved → {log_path}", flush=True)


if __name__ == "__main__":
    asyncio.run(run())
