"""議論全体（負けた主張を含む）と最終回答のカバレッジを、同じスタンス項目で比較する.

既存の atomic coverage は最終回答だけを見る。ここでは同じ項目（stance の原子的な主張）について
  - final   : 最終回答が項目を扱っているか（既存の判定と同じ）
  - dialogue: 議論の全発話（勝った主張も負けた主張も）のどこかが項目を扱っているか
を判定し、「議論では出たのに最終回答に残らなかった項目」（dialogue_only）を数える。

Usage:
    python -m experiments.eval.runners.eval_dialogue_coverage \
      --base-dir logs/experiment_<日時>/turns<N>/raw_dialogue \
      --out logs/experiment_<日時>/turns<N>/eval_result/dialogue_coverage/dialogue_coverage_comparison.json
"""

# ruff: noqa: T201, E402, I001

from __future__ import annotations

import argparse
import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from experiments.eval.runners.eval_atomic_coverage_final import (
    ROOT,
    _collect_logs,
    _EvaluatorModel,
)
from experiments.eval.runners.run_eval import resolve_evaluator_model
from experiments.eval.scoring.evaluation_coverage import _parse_json_response
from experiments.eval.scoring.evaluation_coverage_atomic import (
    evaluate_stance_coverage_atomic,
)
from experiments.eval.scoring.stance_decomposition import extract_stance_items_atomic

DEFAULT_BASE_DIR = ROOT / "logs"

# 長い transcript を先に置き、項目（毎回変わる部分）を後ろに置く: 同じログの項目間で
# プロンプトの前半が共通になり、キャッシュが効いて費用が下がる。
DIALOGUE_COVERAGE_INSTRUCTION = """
You are an evaluator LLM. Judge whether the debate transcript below addresses the claim given after it.

Addressed: at least one turn of the transcript engages with the claim's specific substance
(supports it, qualifies it, or argues against it), whichever side makes the point.

Not addressed: the transcript is silent on the claim, or only generically consistent
with it without engaging its substance.

Debate transcript:
{transcript}

Claim:
{item}

Respond ONLY with a JSON object: {{"addressed": <bool>}}
""".strip()


def render_argument(argument: Any) -> str:
    """発話の本文を読める文章にする（schema の構造化 Argument は規則を文に直す）."""
    if isinstance(argument, str):
        try:
            parsed = json.loads(argument)
        except json.JSONDecodeError:
            return argument
        argument = parsed if isinstance(parsed, dict) else argument
    if not isinstance(argument, dict):
        return str(argument)
    body = argument.get("Argument", argument)
    if not isinstance(body, dict):
        return str(body)
    lines: list[str] = []
    for rule in body.get("rules", []):
        ante = rule.get("antecedent", {})
        strong = "; ".join(ante.get("strong", []))
        weak = "; ".join(ante.get("weak_negation", []))
        parts = [p for p in (strong, f"assuming {weak}" if weak else "") if p]
        lines.append(f"{' | '.join(parts)} => {rule.get('consequent', '')}")
    return "\n".join(lines) or json.dumps(body, ensure_ascii=False)


def build_transcript(log: dict[str, Any]) -> str:
    """dialogue_history の全発話を、話者・役割つきの1本のテキストにする."""
    turns = []
    for i, rec in enumerate(log.get("dialogue_history", []), start=1):
        role = rec.get("type") or f"round {rec.get('round', '?')}"
        if rec.get("attack"):
            role += f"/{rec['attack']}"
        turns.append(f"[{i}] {rec.get('agent', '?')} ({role}):\n{render_argument(rec.get('argument'))}")
    return "\n\n".join(turns)


def _judge(model: _EvaluatorModel, item: str, transcript: str) -> bool | None:
    prompt = DIALOGUE_COVERAGE_INSTRUCTION.format(item=item, transcript=transcript)
    try:
        value = _parse_json_response(model.invoke(prompt)).get("addressed")
        if not isinstance(value, bool):
            raise ValueError(f"expected bool, got: {value!r}")
        return value
    except Exception as exc:  # noqa: BLE001 - 評価失敗を診断出力して継続する
        print(f"Dialogue coverage evaluation failed for item {item[:60]!r}: {exc}")
        return None


def _evaluate_one(log_path: Path, model_name: str) -> dict[str, Any]:
    log = json.loads(log_path.read_text(encoding="utf-8"))
    model = _EvaluatorModel(model_name)
    items = extract_stance_items_atomic(log.get("agent1_stance") or "") + extract_stance_items_atomic(
        log.get("agent2_stance") or ""
    )
    final = evaluate_stance_coverage_atomic(log, model)["addressed"] or [None] * len(items)
    transcript = build_transcript(log)
    dialogue = [_judge(model, item, transcript) for item in items]

    pairs = [(f, d) for f, d in zip(final, dialogue, strict=True) if isinstance(f, bool) and isinstance(d, bool)]
    total = len(items)
    return {
        "file": log_path.name,
        "topic": log_path.parent.name,
        "category": log_path.parent.parent.name,
        "method": log.get("method") or log.get("mode"),
        "total": total,
        "final_covered": sum(f for f, _ in pairs),
        "dialogue_covered": sum(d for _, d in pairs),
        # 議論では扱われたが、最終回答には残らなかった項目
        "dialogue_only": sum(1 for f, d in pairs if d and not f),
        # 最終回答にだけ現れた項目（統合や最終回答の生成で加わったもの）
        "final_only": sum(1 for f, d in pairs if f and not d),
        "valid": len(pairs),
        "transcript_chars": len(transcript),
        "final_answer_chars": len(log.get("final_answer") or ""),
        "dialogue_turns": len(log.get("dialogue_history", [])),
        "items": items,
        "final_addressed": final,
        "dialogue_addressed": dialogue,
    }


def _ratio(num: int, den: int) -> float | None:
    return round(num / den, 4) if den else None


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_method: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_method.setdefault(row["method"], []).append(row)
    summary: dict[str, Any] = {}
    for method, group in sorted(by_method.items()):
        valid = sum(r["valid"] for r in group)
        final_covered = sum(r["final_covered"] for r in group)
        dialogue_covered = sum(r["dialogue_covered"] for r in group)
        answer_chars = sum(r["final_answer_chars"] for r in group)
        summary[method] = {
            "n": len(group),
            "final_coverage": _ratio(sum(r["final_covered"] for r in group), valid),
            "dialogue_coverage": _ratio(sum(r["dialogue_covered"] for r in group), valid),
            # 議論で扱われた項目のうち、最終回答にも残った割合（高いほど取りこぼしが少ない）
            "retention": _ratio(final_covered, dialogue_covered),
            # 最終回答 1,000 字あたりのカバレッジ（高いほど「最小で高い」）
            "final_per_1k_chars": (
                round(final_covered / valid / (answer_chars / len(group) / 1000), 4)
                if valid and answer_chars
                else None
            ),
            "dialogue_only_rate": _ratio(sum(r["dialogue_only"] for r in group), valid),
            "final_only_rate": _ratio(sum(r["final_only"] for r in group), valid),
            "final_answer_chars_mean": round(sum(r["final_answer_chars"] for r in group) / len(group)),
            "transcript_chars_mean": round(sum(r["transcript_chars"] for r in group) / len(group)),
        }
    return summary


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=None)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--base-dir", type=Path, default=DEFAULT_BASE_DIR)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    model_name = resolve_evaluator_model(args.model)
    log_paths = _collect_logs(args.base_dir.resolve(), None)
    print(f"Evaluating {len(log_paths)} logs (dialogue vs final coverage, {model_name}) ...", flush=True)

    rows: list[dict[str, Any]] = []
    lock = threading.Lock()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(_evaluate_one, p, model_name): p for p in log_paths}
        for future in as_completed(futures):
            row = future.result()
            with lock:
                rows.append(row)
                print(
                    f"[{len(rows):03d}/{len(log_paths)}] {row['topic']}/{row['file']} "
                    f"final={row['final_covered']} dialogue={row['dialogue_covered']} "
                    f"dialogue_only={row['dialogue_only']} / {row['total']}",
                    flush=True,
                )

    rows.sort(key=lambda r: (r["topic"], r["file"]))
    summary = _aggregate(rows)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps({"summary_by_method": summary, "detail": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nSaved: {args.out}")
    for method, agg in summary.items():
        print(
            f"{method:<12} n={agg['n']} final={agg['final_coverage']} dialogue={agg['dialogue_coverage']} "
            f"retention={agg['retention']} per_1k={agg['final_per_1k_chars']} "
            f"dialogue_only={agg['dialogue_only_rate']}"
        )


if __name__ == "__main__":
    main()
