"""各発言が、同じ陣営の過去の発言と、同じ導出で同じ主張を出し直していないか（反復）を判定する.

「同型の反論の繰り返し」だけを、形式（schema の規則の連鎖か自由文か）に左右されずに測るためのもの。
発言はすべて同じ見た目の文章（:mod:`src.agent.dialogue_transcript`）にして渡し、判定者には
手法名も、攻撃の種類も、決着状態も見せない。

- 判定の単位: 陣営ごとの2回目以降の発言（その陣営の過去の発言がある発言）。
- 主張（claim）: その発言が主張している結論・論点。導出（derivation）: その主張に至る理由・事実・仕組み。
- 判定は3つ。反復と数えるのは ``same_claim_same_derivation`` だけ。
  - ``new_claim``: 過去の発言にない、新しい主張。
  - ``same_claim_new_derivation``: 同じ主張だが、過去にない別の導出で出している（反復としない。別の導出は、
    同じ結論でも新しい根拠になる）。
  - ``same_claim_same_derivation``: 同じ主張を、過去と同じ導出で出し直している（言い換え・例の追加・対象の付け替えも含む）。

出力は ``<source>/turns<N>/eval_result/turn_novelty/turn_novelty.json``。

Usage:
    python -m experiments.eval.runners.eval_turn_novelty \
      --source logs/experiment_20261007_213516:schema,no_schema \
      --source logs/fin:free_debate,mad,schema,no_schema \
      --source logs/experiment_20261006_175518:mad_synthesis [--turns 20] [--limit 2]
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
from typing import Any, Literal

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

load_dotenv(ROOT / ".env")

from experiments.eval.runners.run_eval import resolve_evaluator_model
from src.agent.dialogue_transcript import render_argument_text

PROMPT = """Below is part of a debate on the question. Two sides, AG1 and AG2, argue in turn. You are shown
one turn written by {agent}, together with every EARLIER turn written by the same side, {agent}.

For the turn under review, identify (1) its CLAIM: the conclusion or point it asserts, and (2) its DERIVATION: the
premises, reasons, facts, or mechanism by which it reaches that claim. Then compare with {agent}'s earlier turns:

- new_claim: the claim is not one {agent} already asserted in an earlier turn.
- same_claim_new_derivation: the claim is one {agent} already asserted, BUT it is reached through a derivation that
  none of {agent}'s earlier turns used (a different reason, fact, or mechanism). A different derivation of the
  same conclusion is NOT a repetition.
- same_claim_same_derivation: the claim is one {agent} already asserted AND it is reached through the same
  underlying derivation as an earlier turn. Rewording, adding an example or more detail, aiming it at a different
  part of the opponent's argument, or reframing does not make a new derivation.

Judge by meaning, not by wording or format. If the claim is new, the derivation cannot be a repeat.

<question>
{question}
</question>

<earlier_turns_by_{agent}>
{earlier}
</earlier_turns_by_{agent}>

<turn_under_review>
{turn}
</turn_under_review>

If the claim was asserted before, name the number of the earlier turn whose claim it matches most closely."""


class NoveltyJudgement(BaseModel):
    """1 発言についての判定."""

    claim: str = Field(
        description="The claim (conclusion) the turn under review asserts, in one sentence."
    )
    verdict: Literal[
        "new_claim", "same_claim_new_derivation", "same_claim_same_derivation"
    ] = Field(
        description="Whether the claim is new, an old claim with a new derivation, or an old claim with an old derivation."
    )
    closest_earlier_turn: int | None = Field(
        default=None,
        description="Number of the earlier turn whose claim it matches most closely (if not a new claim).",
    )
    reason: str = Field(
        description="One sentence: how the derivation compares with the closest earlier turn."
    )


REPEAT = "same_claim_same_derivation"


def collect(source: Path, methods: set[str], turns: set[int] | None) -> list[Path]:
    """対象のログを集める。手法はログの method で判定する."""
    found: list[Path] = []
    for path in sorted(source.glob("turns*/raw_dialogue/*/*/*.json")):
        number = int(re.sub(r"\D", "", path.parents[3].name))
        if turns is not None and number not in turns:
            continue
        if json.loads(path.read_text(encoding="utf-8")).get("method") in methods:
            found.append(path)
    return found


def reviewable_turns(history: list[dict[str, Any]]) -> list[int]:
    """その陣営の過去の発言がある発言の位置（0 始まり）."""
    seen: set[str] = set()
    out: list[int] = []
    for index, turn in enumerate(history):
        agent = str(turn.get("agent"))
        if agent in seen:
            out.append(index)
        seen.add(agent)
    return out


def build_prompt(question: str, history: list[dict[str, Any]], index: int) -> str:
    """Build the judge prompt for the turn at ``index``（過去の自分の発言だけを見せる）."""
    agent = str(history[index].get("agent"))
    earlier = "\n\n".join(
        f"[Turn {i + 1}]\n{render_argument_text(history[i].get('argument'))}"
        for i in range(index)
        if history[i].get("agent") == agent
    )
    return PROMPT.format(
        agent=agent,
        question=question,
        earlier=earlier,
        turn=f"[Turn {index + 1}]\n{render_argument_text(history[index].get('argument'))}",
    )


def _judge(model_name: str, prompt: str) -> NoveltyJudgement:
    structured = ChatOpenAI(model=model_name).with_structured_output(NoveltyJudgement)
    result = structured.invoke(prompt)
    return (
        result
        if isinstance(result, NoveltyJudgement)
        else NoveltyJudgement.model_validate(result)
    )


def evaluate_log(model_name: str, path: Path) -> dict[str, Any]:
    """1 つのログの、対象の発言すべてを判定する。1 発言の失敗は verdict=None で記録して続ける."""
    log = json.loads(path.read_text(encoding="utf-8"))
    history = list(log.get("dialogue_history") or [])
    rows: list[dict[str, Any]] = []
    for index in reviewable_turns(history):
        base = {
            "turn": index + 1,
            "agent": history[index].get("agent"),
            "type": history[index].get("type"),
        }
        try:
            judgement = _judge(
                model_name, build_prompt(str(log.get("question", "")), history, index)
            )
        except Exception as exc:  # noqa: BLE001 - 1 発言の失敗で全体を止めない
            print(f"failed: {path.name} turn {index + 1}: {exc}", flush=True)
            rows.append(
                {
                    **base,
                    "verdict": None,
                    "claim": None,
                    "closest_earlier_turn": None,
                    "reason": f"failed: {exc}",
                }
            )
            continue
        rows.append(
            {
                **base,
                "claim": judgement.claim,
                "verdict": judgement.verdict,
                "closest_earlier_turn": judgement.closest_earlier_turn,
                "reason": judgement.reason,
            }
        )
    judged_rows = [r for r in rows if r["verdict"] is not None]
    judged = len(judged_rows)
    repeated = sum(r["verdict"] == REPEAT for r in judged_rows)
    return {
        "file": path.name,
        "topic": path.parent.name,
        "category": path.parent.parent.name,
        "method": log.get("method"),
        "n_judged": judged,
        "n_failed": len(rows) - judged,
        "n_repeat": repeated,
        "repeat_rate": round(repeated / judged, 4) if judged else None,
        "turns": rows,
    }


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    """手法ごとの反復率（ログごとの率の平均）、判定の内訳、発言の種類別の反復率."""
    summary: dict[str, Any] = {}
    for method in sorted({str(r["method"]) for r in results}):
        logs = [
            r for r in results if r["method"] == method and r["repeat_rate"] is not None
        ]
        by_type: dict[str, list[bool]] = defaultdict(list)
        counts: dict[str, int] = defaultdict(int)
        for log in logs:
            for turn in log["turns"]:
                if turn["verdict"] is None:
                    continue
                by_type[str(turn["type"])].append(turn["verdict"] == REPEAT)
                counts[turn["verdict"]] += 1
        total = sum(counts.values())
        summary[method] = {
            "n_logs": len(logs),
            "repeat_rate_mean": round(st.mean(r["repeat_rate"] for r in logs), 4)
            if logs
            else None,
            "repeats_per_log": round(st.mean(r["n_repeat"] for r in logs), 2)
            if logs
            else None,
            "verdict_share": {k: round(v / total, 4) for k, v in sorted(counts.items())}
            if total
            else {},
            "repeat_by_turn_type": {
                k: round(sum(v) / len(v), 4) for k, v in sorted(by_type.items())
            },
        }
    return summary


def parse_source(value: str) -> tuple[Path, frozenset[str]]:
    """``<実験フォルダ>:<手法,手法>`` を解釈する."""
    path, _, methods = value.rpartition(":")
    if not path or not methods:
        raise argparse.ArgumentTypeError(
            f"形式は <実験フォルダ>:<手法,手法> です: {value!r}"
        )
    return Path(path), frozenset(m.strip() for m in methods.split(",") if m.strip())


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--source",
        action="append",
        type=parse_source,
        required=True,
        help="<実験フォルダ>:<手法,手法>（複数可）。",
    )
    parser.add_argument(
        "--turns",
        default=None,
        help="対象のターン数を ',' 区切りで（例: 20）。省略で全部。",
    )
    parser.add_argument(
        "--model", default=None, help="評価モデル（既定: 環境変数 MODEL）。"
    )
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="試運転用: 各 --source で評価するログ数の上限。",
    )
    args = parser.parse_args()

    turns = {int(t) for t in args.turns.split(",") if t.strip()} if args.turns else None
    model_name = resolve_evaluator_model(args.model)
    paths: list[Path] = []
    for root, methods in args.source:
        found = collect(root.resolve(), set(methods), turns)
        paths += found[: args.limit] if args.limit else found
    calls = sum(
        len(
            reviewable_turns(
                json.loads(p.read_text(encoding="utf-8")).get("dialogue_history") or []
            )
        )
        for p in paths
    )
    print(
        f"{len(paths)} ログ、約 {calls} 回の判定（{model_name}, workers={args.workers}）",
        flush=True,
    )

    results: list[tuple[Path, dict[str, Any]]] = []
    lock = threading.Lock()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(evaluate_log, model_name, p): p for p in paths}
        for done, future in enumerate(as_completed(futures), start=1):
            with lock:
                results.append((futures[future], future.result()))
                print(
                    f"[{done:03d}/{len(paths)}] {futures[future].parent.name}/{futures[future].name}",
                    flush=True,
                )

    results.sort(
        key=lambda item: (
            str(item[0].parents[3]),
            item[1]["topic"],
            str(item[1]["method"]),
            item[1]["file"],
        )
    )
    by_turns: dict[Path, list[dict[str, Any]]] = defaultdict(list)
    for path, row in results:
        by_turns[path.parents[3]].append(row)
    for turn_dir, rows in sorted(by_turns.items()):
        out = turn_dir / "eval_result" / "turn_novelty" / "turn_novelty.json"
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
    by_root: dict[Path, list[dict[str, Any]]] = defaultdict(list)
    for path, row in results:
        by_root[path.parents[4]].append(row)
    print("\n手法ごとの反復率（実験フォルダごと）:")
    for root, rows in sorted(by_root.items()):
        print(f"  {root.name}: {json.dumps(summarize(rows), ensure_ascii=False)}")


if __name__ == "__main__":
    main()
