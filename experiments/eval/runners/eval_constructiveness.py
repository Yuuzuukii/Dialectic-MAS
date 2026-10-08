"""議論そのものの建設性（Constructiveness、1〜10 点）を、実験フォルダの全ログに対して採点する.

プロンプトは ``evaluation_rubrics.CONSTRUCTIVENESS_INSTRUCTION``（非建設的な応答の割合で採点:
的外れ・一般論・自分の前の発言の繰り返し・適応しない再主張）。入力は議論部分だけで、最終回答と
統合ルールは含めない（``EVAL_INCLUDE_INTEGRATED_RULES=0`` と同じ）。schema の JSON は自然文に直す。

``--source <実験フォルダ>:<手法,手法>`` を複数指定できる。手法はログの ``method`` で判定する。
1 本のログの失敗で他の結果を失わないよう、失敗した 1 本は ``null`` として記録して続ける。

出力は ``<実験フォルダ>/turns<N>/eval_result/constructiveness/constructiveness.json``。

Usage:
    python -m experiments.eval.runners.eval_constructiveness \
      --source logs/experiment_20261007_213516:schema,no_schema \
      --source logs/fin:free_debate,mad,schema,no_schema \
      --source logs/experiment_20261006_175518:mad_synthesis [--limit 4]
"""

# ruff: noqa: T201, E402, I001

from __future__ import annotations

import argparse
import json
import re
import statistics as st
import sys
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import os

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv(ROOT / ".env")
# 統合ルールの文面を記録に入れない（手法間で記録の長さが偏らないように）。
os.environ["EVAL_INCLUDE_INTEGRATED_RULES"] = "0"

from experiments.eval.runners.run_eval import resolve_evaluator_model
from experiments.eval.scoring.evaluation_rubrics import (
    evaluate_constructiveness_debate_only,
)


class _Evaluator:
    """ChatOpenAI を、``.model`` と ``.invoke(prompt) -> str`` を持つ形に包む."""

    def __init__(self, model_name: str) -> None:
        self.model = model_name
        self._client = ChatOpenAI(model=model_name)

    def invoke(self, prompt: str) -> str:
        content = self._client.invoke(prompt).content
        return (
            content
            if isinstance(content, str)
            else "\n".join(str(part) for part in content)
        )


def parse_source(value: str) -> tuple[Path, frozenset[str]]:
    """``<実験フォルダ>:<手法,手法>`` を解釈する."""
    path, _, methods = value.rpartition(":")
    if not path or not methods:
        raise argparse.ArgumentTypeError(
            f"形式は <実験フォルダ>:<手法,手法> です: {value!r}"
        )
    return Path(path), frozenset(m.strip() for m in methods.split(",") if m.strip())


def collect(root: Path, methods: frozenset[str]) -> list[Path]:
    """対象のログを集める."""
    found: list[Path] = []
    for path in sorted(root.glob("turns*/raw_dialogue/*/*/*.json")):
        if json.loads(path.read_text(encoding="utf-8")).get("method") in methods:
            found.append(path)
    return found


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """手法ごとの本数・採点できた本数・平均."""
    out: dict[str, Any] = {}
    for method in sorted({str(r["method"]) for r in rows}):
        scores = [
            r["constructiveness"]
            for r in rows
            if r["method"] == method and r["constructiveness"] is not None
        ]
        total = sum(1 for r in rows if r["method"] == method)
        out[method] = {
            "n_logs": total,
            "n_scored": len(scores),
            "constructiveness_mean": round(st.mean(scores), 3) if scores else None,
        }
    return out


def evaluate_one(evaluator: _Evaluator, path: Path) -> dict[str, Any]:
    """1 本のログを採点する。失敗しても例外は投げず、None を記録する."""
    log = json.loads(path.read_text(encoding="utf-8"))
    try:
        result = evaluate_constructiveness_debate_only(log, evaluator)
        score = result.get("constructiveness")
    except Exception as exc:  # noqa: BLE001 - 1 本の失敗で全体を止めない
        print(f"failed: {path.name}: {exc}", flush=True)
        score = None
    return {
        "file": path.name,
        "topic": path.parent.name,
        "category": path.parent.parent.name,
        "method": log.get("method"),
        "turns": int(re.sub(r"\D", "", path.parents[3].name)),
        "constructiveness": score if isinstance(score, int | float) else None,
        "evaluator_model": evaluator.model,
    }


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--source", action="append", type=parse_source, required=True)
    parser.add_argument(
        "--model", default=None, help="評価モデル（既定: 環境変数 MODEL）。"
    )
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="試運転用: 各 --source で採点するログ数の上限。",
    )
    args = parser.parse_args()

    model_name = resolve_evaluator_model(args.model)
    evaluator = _Evaluator(model_name)
    jobs: list[tuple[Path, Path]] = []  # (実験フォルダ, ログ)
    for root, methods in args.source:
        paths = collect(root.resolve(), methods)
        jobs += [
            (root.resolve(), p) for p in (paths[: args.limit] if args.limit else paths)
        ]
    print(f"{len(jobs)} ログ（{model_name}, workers={args.workers}）", flush=True)

    results: dict[tuple[Path, int], list[dict[str, Any]]] = defaultdict(list)
    lock = threading.Lock()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(evaluate_one, evaluator, path): (root, path)
            for root, path in jobs
        }
        for done, future in enumerate(as_completed(futures), start=1):
            root, path = futures[future]
            row = future.result()
            with lock:
                results[(root, row["turns"])].append(row)
                print(
                    f"[{done:03d}/{len(jobs)}] {row['method']} {path.parent.name} -> {row['constructiveness']}",
                    flush=True,
                )

    for (root, turns), rows in sorted(results.items()):
        rows.sort(key=lambda r: (str(r["method"]), r["topic"], r["file"]))
        out = (
            root
            / f"turns{turns}"
            / "eval_result"
            / "constructiveness"
            / "constructiveness.json"
        )
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(
                {"summary": summarize(rows), "detail": rows},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"Saved: {out}")
    print("\n手法ごとの平均（実験フォルダごと）:")
    by_root: dict[Path, list[dict[str, Any]]] = defaultdict(list)
    for (root, _), rows in results.items():
        by_root[root] += rows
    for root, rows in by_root.items():
        print(f"  {root.name}: {json.dumps(summarize(rows), ensure_ascii=False)}")


if __name__ == "__main__":
    main()
