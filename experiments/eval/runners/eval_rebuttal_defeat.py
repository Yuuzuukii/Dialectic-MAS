"""議論中に出た反論を、最終回答が退けられているかを評価する（案A: 各手法自身の議論の反論）.

1. 反論の抽出: 議論の全発話から、相手の立場や主張に向けられた反論を LLM（OpenAI）で列挙する。
   全手法で同じ抽出を使う（free_debate / mad には rebut・undercut のラベルがないため）。
2. 判定: 最終回答と反論 1 件ずつを TypeSafe の Jev（System One）に渡し、Noul 質問 3 つに答えさせる。
   Noul の値は「yes である確率」で、0.5 付近は確信のない判定、0/1 に近いほど確信のある判定。
     - addresses : 最終回答は、反論の根拠（事実・前提）を扱っているか（通りすがりの言及は不可）
     - rejects   : その反論は、最終回答に対して効かないか（条件つきの採用や譲歩では効いたままなので不可）
     - still_valid: その反論は、最終回答に対して実際に効いているか（rejects と表裏）
   主指標は still_valid の平均（低いほど、反論が最終回答に効いていない）。確率は 0.5 付近が確信のない判定で、
   閾値は人手で数件を確認して決める。参考に、退けられた = addresses 高 かつ rejects 高 かつ still_valid 低
   （閾値 --threshold、既定 0.5）の割合も出す。

環境変数: OPENAI_API_KEY（抽出）, TYPESAFE_API_KEY（判定）。.env から読む。

Usage:
    python -m experiments.eval.runners.eval_rebuttal_defeat \
      --base-dir logs/experiment_<日時>/turns<N>/raw_dialogue \
      --out logs/experiment_<日時>/turns<N>/eval_result/rebuttal_defeat/rebuttal_defeat_comparison.json
    # 少数だけ試す（費用確認用）: --limit 2
"""

# ruff: noqa: T201, E402, I001

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from experiments.eval.runners.eval_atomic_coverage_final import (
    ROOT,
    _collect_logs,
    _EvaluatorModel,
)
from experiments.eval.runners.eval_dialogue_coverage import build_transcript
from experiments.eval.runners.run_eval import DEFAULT_EVALUATOR_MODEL
from experiments.eval.scoring.evaluation_coverage import _parse_json_response

from typesafe_sdk import AsyncTypeSafeClient, Noul, NoulAnswer, TypeSafeError

DEFAULT_BASE_DIR = ROOT / "logs"

EXTRACT_INSTRUCTION = """
You are an analyst. Below is a debate transcript between two agents and the stances they started from.
List every distinct rebuttal raised during the debate: a statement in which one agent objects to,
refutes, or undermines the other agent's claim, reasoning, or underlying assumption.

Rules:
- Include rebuttals whether or not they were later answered, conceded, or withdrawn.
- Merge near-duplicates (the same objection restated) into one entry.
- Make each entry self-contained: a reader who has not seen the transcript must understand it.
- Do not invent objections that are not in the transcript.

Agent 1 initial stance:
{stance1}

Agent 2 initial stance:
{stance2}

Debate transcript:
{transcript}

Respond ONLY with JSON:
{{"rebuttals": [{{"raised_by": "<agent name>", "target": "<the claim, reasoning, or assumption attacked>", "objection": "<the objection, self-contained>", "turn": <int, turn number where it first appears>}}]}}
""".strip()

NOUL_QUESTIONS = {
    "addresses": (
        "The final answer deals with the specific ground the rebuttal relies on (the fact or assumption behind the "
        "objection), e.g. by taking it into account or choosing an option for which it does not hold. "
        "Merely mentioning the topic in passing does not count."
    ),
    "rejects": (
        "The rebuttal does not apply to the final answer: given what the final answer actually recommends or concludes, "
        "the objection has no force. A final answer that only makes its position conditional on the objection being "
        "false, or that concedes the objection, does not count."
    ),
    "still_valid": (
        "The rebuttal still applies to the final answer: the objection has force against what the final answer "
        "actually recommends or concludes."
    ),
}


async def _extract_rebuttals(model: _EvaluatorModel, log: dict[str, Any]) -> list[dict[str, Any]]:
    prompt = EXTRACT_INSTRUCTION.format(
        stance1=log.get("agent1_stance") or "",
        stance2=log.get("agent2_stance") or "",
        transcript=build_transcript(log),
    )
    reply = await asyncio.to_thread(model.invoke, prompt)
    rebuttals = _parse_json_response(reply).get("rebuttals", [])
    return [r for r in rebuttals if isinstance(r, dict) and r.get("objection")]


async def _judge_one(
    client: AsyncTypeSafeClient, final_answer: str, rebuttal: dict[str, Any]
) -> dict[str, float | None]:
    state: dict[str, Any] = {"final_answer": final_answer, "rebuttal": rebuttal}
    questions = {key: Noul(instructions=text) for key, text in NOUL_QUESTIONS.items()}
    try:
        response = await client.system_one(state, questions)
    except TypeSafeError as exc:
        print(f"Jev judgement failed: {exc}")
        return {key: None for key in NOUL_QUESTIONS}
    answers = {key: response.answers[key] for key in NOUL_QUESTIONS}
    return {key: float(a.noul) for key, a in answers.items() if isinstance(a, NoulAnswer)}


def is_defeated(scores: dict[str, float | None], threshold: float) -> bool | None:
    """Return True when all three Noul answers reach the threshold on the defeated side, None on a failed judgement."""
    if any(v is None for v in scores.values()):
        return None
    return (
        scores["addresses"] >= threshold  # type: ignore[operator]
        and scores["rejects"] >= threshold  # type: ignore[operator]
        and scores["still_valid"] <= 1 - threshold  # type: ignore[operator]
    )


async def _evaluate_one(
    log_path: Path,
    model: _EvaluatorModel,
    client: AsyncTypeSafeClient,
    cache_dir: Path,
    semaphore: asyncio.Semaphore,
    threshold: float,
) -> dict[str, Any]:
    log = json.loads(log_path.read_text(encoding="utf-8"))
    final_answer = (log.get("final_answer") or "").strip()
    cache = cache_dir / f"{log_path.parent.name}__{log_path.stem}.json"  # 抽出結果は再利用する
    if cache.exists():
        rebuttals = json.loads(cache.read_text(encoding="utf-8"))
    else:
        async with semaphore:
            rebuttals = await _extract_rebuttals(model, log)
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(rebuttals, ensure_ascii=False, indent=2), encoding="utf-8")

    async def judge(rebuttal: dict[str, Any]) -> dict[str, float | None]:
        async with semaphore:
            return await _judge_one(client, final_answer, rebuttal)

    scores = await asyncio.gather(*(judge(r) for r in rebuttals)) if final_answer else []
    judged = [
        {**r, "scores": s, "defeated": is_defeated(s, threshold)} for r, s in zip(rebuttals, scores, strict=False)
    ]
    valid = [j for j in judged if j["defeated"] is not None]
    return {
        "file": log_path.name,
        "topic": log_path.parent.name,
        "category": log_path.parent.parent.name,
        "method": log.get("method") or log.get("mode"),
        "rebuttal_count": len(rebuttals),
        "valid": len(valid),
        "defeated": sum(1 for j in valid if j["defeated"]),
        "rebuttals": judged,
    }


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def _rate(values: list[float], threshold: float) -> float | None:
    return round(sum(v >= threshold for v in values) / len(values), 4) if values else None


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for method in sorted({r["method"] for r in rows}):
        group = [r for r in rows if r["method"] == method]
        valid = sum(r["valid"] for r in group)
        per_log = [r["defeated"] / r["valid"] for r in group if r["valid"]]
        probs = {
            key: [j["scores"][key] for r in group for j in r["rebuttals"] if j["scores"][key] is not None]
            for key in NOUL_QUESTIONS
        }
        summary[method] = {
            "n": len(group),
            "rebuttals_per_log": round(sum(r["rebuttal_count"] for r in group) / len(group), 2),
            # 主指標: 低いほど、反論が最終回答に効いていない
            "still_valid_mean": _mean(probs["still_valid"]),
            "still_valid_ge_0.7_rate": _rate(probs["still_valid"], 0.7),
            "addresses_mean": _mean(probs["addresses"]),
            "rejects_mean": _mean(probs["rejects"]),
            "defeat_rate_micro": round(sum(r["defeated"] for r in group) / valid, 4) if valid else None,
            "defeat_rate_per_log_mean": round(sum(per_log) / len(per_log), 4) if per_log else None,
        }
    return summary


async def _run(args: argparse.Namespace) -> None:
    model = _EvaluatorModel(args.model)
    log_paths = _collect_logs(args.base_dir.resolve(), None)[: args.limit or None]
    print(f"Evaluating {len(log_paths)} logs (rebuttal defeat, extractor={model.model}) ...", flush=True)
    cache_dir = args.out.parent / "rebuttals"
    semaphore = asyncio.Semaphore(args.concurrency)
    async with AsyncTypeSafeClient() as client:
        tasks = [
            asyncio.create_task(_evaluate_one(p, model, client, cache_dir, semaphore, args.threshold))
            for p in log_paths
        ]
        rows: list[dict[str, Any]] = []
        for done in asyncio.as_completed(tasks):
            row = await done
            rows.append(row)
            print(
                f"[{len(rows):03d}/{len(log_paths)}] {row['topic']}/{row['file']} "
                f"defeated={row['defeated']}/{row['valid']} (rebuttals={row['rebuttal_count']})",
                flush=True,
            )
    rows.sort(key=lambda r: (r["topic"], r["file"]))
    summary = _aggregate(rows)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps({"threshold": args.threshold, "summary_by_method": summary, "detail": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nSaved: {args.out}")
    for method, agg in summary.items():
        print(f"{method:<12} {agg}")


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model", default=DEFAULT_EVALUATOR_MODEL, help="反論抽出に使う OpenAI モデル（環境変数 MODEL は見ない）。"
    )
    parser.add_argument("--base-dir", type=Path, default=DEFAULT_BASE_DIR)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--threshold", type=float, default=0.5, help="確信度の閾値（人手で数件確認して決める）。")
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--limit", type=int, default=0, help="先頭の N ログだけ評価（0 なら全部）。")
    asyncio.run(_run(parser.parse_args()))


if __name__ == "__main__":
    main()
