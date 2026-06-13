"""Compare schema vs no-schema unified logs for ONE category.

Scores every result log of each topic with the same LLM evaluator, averages per topic and per
category, and writes the result as JSON plus a console table.

Usage:
    python src/eval/compare_category.py <category> [--model gpt-5-mini]
"""

# print による結果出力と、sys.path 追加後の import はこの評価スクリプトでは意図的。
# ruff: noqa: T201, E402

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from src.eval.evaluation import (
    aggregate_scores,
    build_eval_input,
    build_eval_input_no_schema,
    evaluate_with_llm,
)
from src.eval.run_eval import _EvaluatorModel, resolve_evaluator_model

SCHEMA_ROOT = ROOT / "logs"
NO_SCHEMA_ROOT = ROOT / "logs"
SCORES_DIR = ROOT / "eval" / "scores"


def _resolve_root(path: Path) -> Path:
    if path.exists() or path.is_absolute():
        return path
    root_relative = ROOT / path
    return root_relative if root_relative.exists() else path


def _log_method(path: Path) -> str | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    method = data.get("method") or data.get("mode")
    if method == "no-schema":
        return "no_schema"
    return method if method in {"schema", "no_schema"} else None


def _topic_log_files(root: Path, category: str, *, no_schema: bool) -> dict[str, list[Path]]:
    base = root / category
    if not base.is_dir():
        return {}

    topics: dict[str, list[Path]] = {}
    expected_method = "no_schema" if no_schema else "schema"

    for topic_dir in sorted(base.iterdir()):
        if not topic_dir.is_dir():
            continue
        files = [
            log_file
            for log_file in sorted(topic_dir.glob("*.json"))
            if _log_method(log_file) == expected_method
        ]
        if files:
            topics.setdefault(topic_dir.name, []).extend(files)

    return topics


def _score_topic(log_files: list[Path], evaluator: Any, *, no_schema: bool) -> dict[str, Any]:
    builder = build_eval_input_no_schema if no_schema else build_eval_input
    scores: list[dict[str, Any]] = []
    for log_file in sorted(log_files):
        log = json.loads(log_file.read_text(encoding="utf-8"))
        scores.append(evaluate_with_llm(builder(log), evaluator))
    return aggregate_scores(scores)


def _delta(pair: dict[str, Any]) -> float | None:
    s = pair["schema"]["average"]
    n = pair["no_schema"]["average"]
    if isinstance(s, (int, float)) and isinstance(n, (int, float)):
        return round(s - n, 2)
    return None


def compare_category(
    category: str,
    evaluator: Any,
    *,
    schema_root: Path = SCHEMA_ROOT,
    no_schema_root: Path = NO_SCHEMA_ROOT,
) -> dict[str, Any]:
    """1 カテゴリ内の全トピックを採点し、schema/no-schema の比較結果を返す."""
    schema_topics = _topic_log_files(schema_root, category, no_schema=False)
    noschema_topics = _topic_log_files(no_schema_root, category, no_schema=True)
    topics = sorted(set(schema_topics) | set(noschema_topics))

    result_topics: dict[str, Any] = {}
    schema_aggr: list[dict[str, Any]] = []
    noschema_aggr: list[dict[str, Any]] = []

    for topic in topics:
        schema_score = (
            _score_topic(schema_topics[topic], evaluator, no_schema=False)
            if topic in schema_topics else aggregate_scores([])
        )
        noschema_score = (
            _score_topic(noschema_topics[topic], evaluator, no_schema=True)
            if topic in noschema_topics else aggregate_scores([])
        )
        result_topics[topic] = {"schema": schema_score, "no_schema": noschema_score}
        if schema_score["n"]:
            schema_aggr.append(schema_score)
        if noschema_score["n"]:
            noschema_aggr.append(noschema_score)

    category_average: dict[str, Any] = {
        "schema": aggregate_scores(schema_aggr),
        "no_schema": aggregate_scores(noschema_aggr),
    }
    category_average["delta"] = _delta(category_average)

    return {
        "category": category,
        "evaluator_model": getattr(evaluator, "model", "unknown"),
        "topics": result_topics,
        "category_average": category_average,
    }


def _fmt(value: Any) -> str:
    return f"{value:.2f}" if isinstance(value, (int, float)) else "N/A"


def print_category_table(result: dict[str, Any]) -> None:
    """カテゴリの比較結果をトピック別の表として端末に出力する."""
    print(f"\n=== Comparison: {result['category']} (evaluator: {result['evaluator_model']}) ===\n")
    header = f"{'Topic':<30}{'schema':>9}{'no-schema':>12}{'Δ':>9}"
    print(header)
    print("-" * len(header))
    for topic, pair in result["topics"].items():
        s = pair["schema"]["average"]
        n = pair["no_schema"]["average"]
        print(f"{topic[:30]:<30}{_fmt(s):>9}{_fmt(n):>12}{_fmt(_delta(pair)):>9}")
    ca = result["category_average"]
    print("-" * len(header))
    print(
        f"{'CATEGORY AVERAGE':<30}{_fmt(ca['schema']['average']):>9}"
        f"{_fmt(ca['no_schema']['average']):>12}{_fmt(ca['delta']):>9}"
    )
    print("\n(Δ = schema − no-schema; positive means schema scored higher)\n")


def _save(result: dict[str, Any], filename: str) -> Path:
    SCORES_DIR.mkdir(parents=True, exist_ok=True)
    out_path = SCORES_DIR / filename
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def main() -> None:
    """CLI 引数を解析し、指定カテゴリの比較を実行して結果を保存・表示する."""
    parser = argparse.ArgumentParser(description="Compare schema vs no-schema for one category.")
    parser.add_argument("category", help="Category name under logs/.")
    parser.add_argument(
        "--model",
        default=None,
        help="Evaluator model name. Defaults to MODEL from .env, then gpt-5-mini.",
    )
    parser.add_argument(
        "--schema-root",
        type=Path,
        default=SCHEMA_ROOT,
        help="Root containing schema logs (default: logs).",
    )
    parser.add_argument(
        "--no-schema-root",
        type=Path,
        default=NO_SCHEMA_ROOT,
        help="Root containing no-schema logs (default: logs).",
    )
    args = parser.parse_args()
    model = resolve_evaluator_model(args.model)
    schema_root = _resolve_root(args.schema_root)
    no_schema_root = _resolve_root(args.no_schema_root)

    if not (schema_root / args.category).is_dir() and not (no_schema_root / args.category).is_dir():
        print(
            f"No logs found for category '{args.category}' in {schema_root} or {no_schema_root}",
            file=sys.stderr,
        )
        sys.exit(1)

    evaluator = _EvaluatorModel(model)
    print(f"Scoring category '{args.category}' with {model} ...")
    result = compare_category(
        args.category,
        evaluator,
        schema_root=schema_root,
        no_schema_root=no_schema_root,
    )

    print_category_table(result)
    out_path = _save(result, f"{args.category}.json")
    print(f"[system] scores saved → {out_path}")


if __name__ == "__main__":
    main()
