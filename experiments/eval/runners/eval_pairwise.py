"""2 つの手法の最終回答を、エージェントの立場から対比較し、どちらが核心の主張を残しているかを評価する.

SVI は 1 つの回答を単独で評価する（絶対評価）ので、手法間の優劣の理由は出ない。ここでは、
同じトピック・同じターン数・同じ run 番号の 2 つの最終回答（議論の記録は入れない）を並べ、
AG1 と AG2 のそれぞれの立場から、「どちらが自分の核心の主張を残しているか・どちらに満足か」を
理由つきで答えさせる。

- 順序の偏り（先に出した回答を選ぶ）を避けるため、各組を A/B の両方の順序で評価する。
- 回答は手法名を伏せて渡す（A / B のみ）。

出力は ``<source>/turns<N>/eval_result/pairwise/pairwise_<手法X>_vs_<手法Y>.json``。

Usage:
    python -m experiments.eval.runners.eval_pairwise --source logs/fin --methods schema,no_schema [--limit 4]
"""

# ruff: noqa: T201, E402, I001

from __future__ import annotations

import argparse
import json
import re
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

# run 番号の接頭辞 NN_ は任意（--runs 1 のログには付かない）。
_FILENAME_RE = re.compile(r"^(?:(?P<run>\d+)_)?(?P<method>.+)_\d{8}_\d{6}_\d+$")

_AGENTS: tuple[Literal["AG1", "AG2"], ...] = ("AG1", "AG2")

PROMPT = """You are {agent}, one of two debaters. You took part in a debate on the question below, and you
hold the stance given to you. Two different final answers to the same question were written (answers A and B).
Judge them ONLY from your own point of view as {agent}.

<question>
{question}
</question>

<your_stance>
{stance}
</your_stance>

<opponent_stance>
{other_stance}
</opponent_stance>

<answer_A>
{answer_a}
</answer_A>

<answer_B>
{answer_b}
</answer_B>

Compare the two answers:
- Which answer keeps the core claims of YOUR stance better (as a position or as a condition on the conclusion)?
- Which outcome would you be more satisfied with?
Be concrete: name which of your stance's claims survive in each answer, and why that decides your choice.
Answer "tie" only if you genuinely see no difference."""


class PairwiseJudgement(BaseModel):
    """1 つの組・1 つの順序・1 人のエージェントの対比較の判定."""

    core_kept_A: str = Field(description="Which claims of your stance survive in answer A (short; 'none' if none).")
    core_kept_B: str = Field(description="Which claims of your stance survive in answer B (short; 'none' if none).")
    preferred: Literal["A", "B", "tie"] = Field(description="The answer you prefer from your own point of view.")
    reason: str = Field(description="Concrete reason for the preference, in 1-3 sentences.")


def _collect(source: Path, methods: tuple[str, str]) -> dict[tuple[int, str, str, str], dict[str, Path]]:
    """Collect, for each ``(turns, category, topic, run)``, the log path of every method."""
    found: dict[tuple[int, str, str, str], dict[str, Path]] = defaultdict(dict)
    for path in sorted(source.glob("turns*/raw_dialogue/*/*/*.json")):
        match = _FILENAME_RE.match(path.stem)
        if match is None or match.group("method") not in methods:
            continue
        turns = int(re.sub(r"\D", "", path.parents[3].name))
        key = (turns, path.parent.parent.name, path.parent.name, match.group("run") or "00")
        found[key][match.group("method")] = path
    return {k: v for k, v in found.items() if len(v) == len(methods)}


def _judge(
    model_name: str, log_a: dict[str, Any], log_b: dict[str, Any], agent: Literal["AG1", "AG2"]
) -> PairwiseJudgement:
    own, other = ("agent1_stance", "agent2_stance") if agent == "AG1" else ("agent2_stance", "agent1_stance")
    prompt = PROMPT.format(
        agent=agent,
        question=log_a.get("question", ""),
        stance=log_a.get(own, ""),
        other_stance=log_a.get(other, ""),
        answer_a=(log_a.get("final_answer") or "").strip(),
        answer_b=(log_b.get("final_answer") or "").strip(),
    )
    structured = ChatOpenAI(model=model_name).with_structured_output(PairwiseJudgement)
    result = structured.invoke(prompt)
    return result if isinstance(result, PairwiseJudgement) else PairwiseJudgement.model_validate(result)


def _evaluate_pair(
    model_name: str, key: tuple[int, str, str, str], paths: dict[str, Path], methods: tuple[str, str]
) -> list[dict[str, Any]]:
    logs = {m: json.loads(paths[m].read_text(encoding="utf-8")) for m in methods}
    if not all((logs[m].get("final_answer") or "").strip() for m in methods):
        return []
    rows: list[dict[str, Any]] = []
    for first, second in ((methods[0], methods[1]), (methods[1], methods[0])):
        for agent in _AGENTS:
            judgement = _judge(model_name, logs[first], logs[second], agent)
            chosen = {"A": first, "B": second, "tie": "tie"}[judgement.preferred]
            rows.append(
                {
                    "turns": key[0],
                    "category": key[1],
                    "topic": key[2],
                    "run": key[3],
                    "agent": agent,
                    "order": f"{first}_first",
                    "A": first,
                    "B": second,
                    "preferred": judgement.preferred,
                    "preferred_method": chosen,
                    "core_kept_A": judgement.core_kept_A,
                    "core_kept_B": judgement.core_kept_B,
                    "reason": judgement.reason,
                    "files": {m: paths[m].name for m in methods},
                }
            )
    return rows


def _summarize(rows: list[dict[str, Any]], methods: tuple[str, str]) -> dict[str, Any]:
    x, y = methods
    total = len(rows)

    def share(sub: list[dict[str, Any]], what: str) -> float | None:
        return round(sum(r["preferred_method"] == what for r in sub) / len(sub), 4) if sub else None

    summary: dict[str, Any] = {
        "methods": list(methods),
        "n_judgements": total,
        f"share_{x}": share(rows, x),
        f"share_{y}": share(rows, y),
        "share_tie": share(rows, "tie"),
        # 位置の偏り: A（先に出した回答）を選んだ割合。0.5 から大きく離れていれば、順序の影響が大きい。
        "share_chose_A": round(sum(r["preferred"] == "A" for r in rows) / total, 4) if total else None,
    }
    for agent in ("AG1", "AG2"):
        sub = [r for r in rows if r["agent"] == agent]
        summary[f"{agent}_share_{x}"] = share(sub, x)
        summary[f"{agent}_share_{y}"] = share(sub, y)
    for turns in sorted({r["turns"] for r in rows}):
        sub = [r for r in rows if r["turns"] == turns]
        summary[f"turns{turns}_share_{x}"] = share(sub, x)
    # 順序を入れ替えても同じ手法が選ばれた判定（順序に左右されない選好）の割合
    grouped: dict[tuple[Any, ...], list[str]] = defaultdict(list)
    for r in rows:
        grouped[(r["turns"], r["category"], r["topic"], r["run"], r["agent"])].append(r["preferred_method"])
    consistent = [v for v in grouped.values() if len(v) == 2 and v[0] == v[1] and v[0] != "tie"]
    summary["order_consistent_share"] = round(len(consistent) / len(grouped), 4) if grouped else None
    summary[f"order_consistent_prefers_{x}"] = sum(v[0] == x for v in consistent)
    summary[f"order_consistent_prefers_{y}"] = sum(v[0] == y for v in consistent)
    return summary


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", type=Path, required=True, help="対象の実験フォルダ（例: logs/fin）。")
    parser.add_argument("--methods", default="schema,no_schema", help="比べる 2 手法を ',' 区切りで。")
    parser.add_argument("--model", default=None, help="評価モデル（既定: 環境変数 MODEL）。")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--limit", type=int, default=None, help="試運転用: 評価する組の数の上限。")
    args = parser.parse_args()

    names = tuple(m.strip() for m in args.methods.split(",") if m.strip())
    if len(names) != 2:
        raise SystemExit("--methods には、比べる 2 手法を指定してください。")
    methods: tuple[str, str] = (names[0], names[1])
    source = args.source.resolve()
    pairs = _collect(source, methods)
    keys = sorted(pairs)[: args.limit] if args.limit else sorted(pairs)
    model_name = resolve_evaluator_model(args.model)
    print(f"{len(keys)} 組 x 2 エージェント x 2 順序 = {len(keys) * 4} 回（{model_name}, workers={args.workers}）", flush=True)

    rows: list[dict[str, Any]] = []
    lock = threading.Lock()
    done = [0]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(_evaluate_pair, model_name, k, pairs[k], methods): k for k in keys}
        for future in as_completed(futures):
            result = future.result()
            with lock:
                done[0] += 1
                rows.extend(result)
                print(f"[{done[0]:03d}/{len(keys)}] {futures[future]}", flush=True)

    rows.sort(key=lambda r: (r["turns"], r["category"], r["topic"], r["run"], r["agent"], r["order"]))
    for turns in sorted({r["turns"] for r in rows}):
        sub = [r for r in rows if r["turns"] == turns]
        out = source / f"turns{turns}" / "eval_result" / "pairwise" / f"pairwise_{methods[0]}_vs_{methods[1]}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps({"summary": _summarize(sub, methods), "detail": sub}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"Saved: {out}")
    print("\n全ターン数の合算:")
    for key, value in _summarize(rows, methods).items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
