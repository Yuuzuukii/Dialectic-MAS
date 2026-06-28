"""Evaluate a Dialect-MAS run log with an LLM evaluator.

Usage:
    python src/eval/run_eval.py                        # latest log in logs/
    python src/eval/run_eval.py --log logs/foo.json
    python src/eval/run_eval.py --model gpt-4o
"""

# print による結果出力と、sys.path 追加後の import はこの評価スクリプトでは意図的。
# ruff: noqa: T201, E402

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv(ROOT / ".env")

from src.eval.evaluation import (
    AXES,
    build_eval_input,
    efficiency_metrics,
    evaluate_with_llm,
)

DEFAULT_EVALUATOR_MODEL = "gpt-5.4-mini"


def _latest_log(logs_dir: Path) -> Path:
    logs = sorted(logs_dir.rglob("*.json"))
    if not logs:
        print(f"No log files found in {logs_dir}", file=sys.stderr)
        sys.exit(1)
    return logs[-1]


def _load_log(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def _resolve_log_path(raw_path: str) -> Path:
    path = Path(raw_path)
    if path.exists() or path.is_absolute():
        return path
    root_relative = ROOT / path
    return root_relative if root_relative.exists() else path


def resolve_evaluator_model(model_arg: str | None = None) -> str:
    """評価器モデル名を引数・環境変数・既定値の優先順で解決する."""
    return (model_arg or os.getenv("MODEL") or DEFAULT_EVALUATOR_MODEL).strip()


class _EvaluatorModel:
    """Thin wrapper so evaluate_with_llm can call .invoke() and read .model."""

    def __init__(self, model_name: str) -> None:
        self.model = model_name
        self._client = ChatOpenAI(model=model_name)

    def invoke(self, prompt: str) -> str:
        response = self._client.invoke(prompt)
        content = response.content
        if isinstance(content, str):
            return content
        return "\n".join(str(part) for part in content)


def _build_metrics(scores: dict[str, Any], efficiency: dict[str, Any]) -> dict[str, Any]:
    """LLM 採点4軸 + 効率(time/cost/tokens) を1つの metrics dict にまとめる."""
    numeric: list[float] = [
        float(scores[a]) for a in AXES if isinstance(scores.get(a), (int, float))
    ]
    quality_average = round(sum(numeric) / len(numeric), 2) if numeric else None
    metrics = {axis: scores.get(axis) for axis in AXES}
    metrics["quality_average"] = quality_average
    metrics.update(efficiency)
    metrics["evaluator_model"] = scores.get("evaluator_model", "unknown")
    return metrics


def _fmt_num(value: Any, suffix: str = "") -> str:
    return f"{value}{suffix}" if isinstance(value, (int, float)) else "N/A"


def _print_scores(metrics: dict[str, Any], log_path: Path, question: str) -> None:
    labels = {
        "coherence":      "Coherence     ",
        "originality":    "Originality   ",
        "dialecticality": "Dialecticality",
        "validity":       "Validity      ",
    }

    print()
    print("=== Evaluation Result ===")
    print(f"Question   : {question[:80]}{'...' if len(question) > 80 else ''}")
    print(f"Log file   : {log_path}")
    print(f"Evaluator  : {metrics.get('evaluator_model', '—')}")
    print()
    print("Quality scores (LLM judge):")
    for axis in AXES:
        val = metrics.get(axis)
        display = f"{val} / 10" if val is not None else "N/A"
        print(f"  {labels[axis]}: {display}")
    print("  " + "─" * 24)
    avg = metrics.get("quality_average")
    print(f"  Average         : {_fmt_num(avg)}{' / 10' if isinstance(avg, (int, float)) else ''}")
    print()
    print("Efficiency (from run log):")
    print(f"  Elapsed time    : {_fmt_num(metrics.get('elapsed_seconds'), ' s')}")
    print(f"  Total cost      : ${_fmt_num(metrics.get('total_cost_usd'))}")
    print(f"  Total tokens    : {_fmt_num(metrics.get('total_tokens'))}")
    print()
    print("Combined metrics (JSON):")
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    print()


def main() -> None:
    """ログを読み込み、LLM 評価と効率指標を計算して結果を出力する."""
    parser = argparse.ArgumentParser(description="Evaluate a Dialect-MAS run log.")
    parser.add_argument("--log", help="Path to the log JSON file.")
    parser.add_argument(
        "--model",
        default=None,
        help="Evaluator model name. Defaults to MODEL from .env, then gpt-5.4-mini.",
    )
    args = parser.parse_args()
    model = resolve_evaluator_model(args.model)

    logs_dir = ROOT / "logs"
    log_path = _resolve_log_path(args.log) if args.log else _latest_log(logs_dir)

    if not log_path.exists():
        print(f"Log file not found: {log_path}", file=sys.stderr)
        sys.exit(1)

    log = _load_log(log_path)
    method = log.get("method") or log.get("mode")
    mode = "no_schema" if method in {"no_schema", "no-schema"} else "schema"
    eval_input = build_eval_input(log, mode=mode)
    evaluator = _EvaluatorModel(model)

    print(f"Evaluating {log_path.name} with {model} ...")
    scores = evaluate_with_llm(eval_input, evaluator)
    metrics = _build_metrics(scores, efficiency_metrics(log))

    _print_scores(metrics, log_path, eval_input["question"])


if __name__ == "__main__":
    main()
