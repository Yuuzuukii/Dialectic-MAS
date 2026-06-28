"""Compare schema vs no-schema unified logs across ALL categories.

Reuses compare_category for each category, then aggregates a per-category breakdown
and an overall score. Writes JSON plus a console table.

Usage:
    python src/eval/compare_all.py [--model gpt-5.4-mini]
"""

# print による結果出力と、sys.path 追加後の import はこの評価スクリプトでは意図的。
# ruff: noqa: T201, E402

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from src.eval.compare_category import (
    NO_SCHEMA_ROOT,
    SCHEMA_ROOT,
    _delta,
    _fmt,
    _resolve_root,
    _save,
    compare_category,
    print_category_table,
)
from src.eval.evaluation import aggregate_scores
from src.eval.run_eval import _EvaluatorModel, resolve_evaluator_model

_EXCLUDE_DIRS = set[str]()


def _all_categories(schema_root: Path = SCHEMA_ROOT, no_schema_root: Path = NO_SCHEMA_ROOT) -> list[str]:
    cats: set[str] = set()
    for root in (schema_root, no_schema_root):
        if root.is_dir():
            for p in root.iterdir():
                if p.is_dir() and p.name not in _EXCLUDE_DIRS:
                    cats.add(p.name)
    return sorted(cats)


def compare_all(
    evaluator: Any,
    *,
    schema_root: Path = SCHEMA_ROOT,
    no_schema_root: Path = NO_SCHEMA_ROOT,
) -> dict[str, Any]:
    """全カテゴリで schema 版と no-schema 版を比較し、カテゴリ別と総合スコアを返す."""
    categories: dict[str, Any] = {}
    schema_aggr: list[dict[str, Any]] = []
    noschema_aggr: list[dict[str, Any]] = []

    for category in _all_categories(schema_root, no_schema_root):
        print(f"Scoring category '{category}' ...")
        result = compare_category(
            category,
            evaluator,
            schema_root=schema_root,
            no_schema_root=no_schema_root,
        )
        categories[category] = result
        ca = result["category_average"]
        if ca["schema"]["n"]:
            schema_aggr.append(ca["schema"])
        if ca["no_schema"]["n"]:
            noschema_aggr.append(ca["no_schema"])

    overall: dict[str, Any] = {
        "schema": aggregate_scores(schema_aggr),
        "no_schema": aggregate_scores(noschema_aggr),
    }
    overall["delta"] = _delta(overall)

    return {
        "evaluator_model": getattr(evaluator, "model", "unknown"),
        "categories": categories,
        "overall": overall,
    }


def print_overall_table(result: dict[str, Any]) -> None:
    """カテゴリ別内訳と総合スコアの表を端末に出力する."""
    print(f"\n=== Overall comparison (evaluator: {result['evaluator_model']}) ===\n")
    header = f"{'Category':<32}{'schema':>9}{'no-schema':>12}{'Δ':>9}"
    print(header)
    print("-" * len(header))
    for category, cat_result in result["categories"].items():
        ca = cat_result["category_average"]
        print(
            f"{category[:32]:<32}{_fmt(ca['schema']['average']):>9}"
            f"{_fmt(ca['no_schema']['average']):>12}{_fmt(ca['delta']):>9}"
        )
    ov = result["overall"]
    print("-" * len(header))
    print(
        f"{'OVERALL':<32}{_fmt(ov['schema']['average']):>9}"
        f"{_fmt(ov['no_schema']['average']):>12}{_fmt(ov['delta']):>9}"
    )
    print("\n(Δ = schema − no-schema; positive means schema scored higher)\n")


def main() -> None:
    """CLI 引数を解析し、全カテゴリ比較を実行して結果を保存・表示する."""
    parser = argparse.ArgumentParser(description="Compare schema vs no-schema across all categories.")
    parser.add_argument(
        "--model",
        default=None,
        help="Evaluator model name. Defaults to MODEL from .env, then gpt-5.4-mini.",
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
    parser.add_argument("--per-category-table", action="store_true",
                        help="Also print the per-topic table for each category.")
    args = parser.parse_args()
    model = resolve_evaluator_model(args.model)
    schema_root = _resolve_root(args.schema_root)
    no_schema_root = _resolve_root(args.no_schema_root)

    categories = _all_categories(schema_root, no_schema_root)
    if not categories:
        print(f"No category logs found in {schema_root} or {no_schema_root}", file=sys.stderr)
        sys.exit(1)

    evaluator = _EvaluatorModel(model)
    result = compare_all(evaluator, schema_root=schema_root, no_schema_root=no_schema_root)

    if args.per_category_table:
        for cat_result in result["categories"].values():
            print_category_table(cat_result)

    print_overall_table(result)
    out_path = _save(result, "all.json")
    print(f"[system] scores saved → {out_path}")


if __name__ == "__main__":
    main()
