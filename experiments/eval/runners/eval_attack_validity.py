"""議論中の攻撃（defeat / counter）が、実際に対象の論証を攻撃しているかを監査する.

no_schema は論証が自由記述で、Conc / Ass の構造がないため、攻撃が成立しているか（rebut なら対象の結論の否定、
undercut なら対象が依拠する前提・仮定の否定）を、実装は LLM の自己申告でしか確かめていない。schema は、宣言された
対象の文が実在するかを照合する。この監査は、両手法の攻撃を、同じ方法で、別の判定者に確かめさせる。

判定者に渡すもの: 問い、対象の論証の文章、攻撃の文章、攻撃側が宣言した対象の文（あれば）。
手法名、攻撃の種類の宣言、決着状態は見せない。形式（規則列か自由文）は、文章に直して揃える。

判定項目（構造化出力。理由の文を必ず返させる）:

- ``attack_kind``: ``contradicts_conclusion``（対象の結論を否定する）/ ``denies_premise_or_assumption``
  （対象が依拠する前提・仮定を否定する）/ ``both`` / ``neither``（どちらも否定していない。反論・応答になっていない）。
- ``declared_statement_present``: 攻撃側が宣言した対象の文が、対象の論証に、意味として含まれているか（宣言がなければ None）。
- ``reason``: 1 文。

``neither`` は、プロトコル上、攻撃として成立していないもの。

標本: 各手法から、攻撃の発言（type が defeat か counter で、対象の論証がログにあるもの）を、無作為に ``--n`` 件。
schema では、実装が却下した攻撃（attempt_log）も、却下の印を付けて含める（却下の判定と、この監査の一致も見る）。

出力は ``<source>/eval_result/attack_validity/attack_validity.json``。

Usage:
    python -m experiments.eval.runners.eval_attack_validity --source logs/final:schema,no_schema [--n 100] [--seed 0]
"""

# ruff: noqa: T201, E402, I001

from __future__ import annotations

import argparse
import json
import random
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

from experiments.eval.runners.eval_turn_novelty import parse_source
from experiments.eval.runners.run_eval import resolve_evaluator_model
from src.agent.dialogue_transcript import render_argument_text

REJECTED_KINDS = {"rebut_undercut_by_target", "attack_rejected"}

PROMPT = """Below are a question and two arguments from a debate: a TARGET argument and an ATTACK that was aimed at it.
Judge the MEANING, not wording or format (one may be plain prose, the other a chain of conditions and conclusions;
treat them the same).

Decide how the ATTACK relates to the TARGET:

- contradicts_conclusion: the attack asserts something that contradicts the conclusion the target reaches.
- denies_premise_or_assumption: the attack asserts something that denies a premise or assumption the target relies on
  (a step its reasoning needs), without necessarily contradicting its final conclusion.
- both: it does both.
- neither: it does neither. For example, it only argues for a different option, repeats its own position, makes a point
  the target never relied on, or changes the subject. Merely disagreeing in tone or supporting the opposite side in
  general does not count as contradicting the target.

Also say whether the declared target statement (if one is given) corresponds, in meaning, to something the TARGET
actually asserts or relies on.

<question>
{question}
</question>

<target>
{target}
</target>

<attack>
{attack}
</attack>

<declared_target_statement>
{declared}
</declared_target_statement>"""


class AttackJudgement(BaseModel):
    """1 件の攻撃についての判定."""

    attack_kind: Literal["contradicts_conclusion", "denies_premise_or_assumption", "both", "neither"] = Field(
        description="How the attack relates to the target."
    )
    declared_statement_present: bool | None = Field(
        default=None,
        description="Whether the declared target statement corresponds to something the target asserts or relies on; null if no statement was declared.",
    )
    reason: str = Field(description="One sentence explaining the judgement.")


def rejected_ids(log: dict[str, Any]) -> set[str]:
    """実装が却下した攻撃の id（attempt_log の、defeat / counter 段階の却下）."""
    return {
        str(a.get("target_id"))
        for a in (log.get("attempt_log") or [])
        if a.get("kind") in REJECTED_KINDS and a.get("phase") in {"defeat", "counter"}
    }


def attack_turns(log: dict[str, Any]) -> list[dict[str, Any]]:
    """攻撃の発言（defeat / counter で、対象の論証がログにあるもの）を、必要な情報と一緒に返す."""
    history = list(log.get("dialogue_history") or [])
    by_id = {str(t.get("id")): t for t in history}
    rejected = rejected_ids(log)
    out: list[dict[str, Any]] = []
    for index, turn in enumerate(history):
        target = by_id.get(str(turn.get("target_id")))
        if turn.get("type") not in {"defeat", "counter"} or target is None:
            continue
        out.append(
            {
                "turn": index + 1,
                "agent": turn.get("agent"),
                "type": turn.get("type"),
                "declared_attack": turn.get("attack"),
                "declared_statement": turn.get("target_statement"),
                "rejected_by_implementation": str(turn.get("id")) in rejected,
                "target_text": render_argument_text(target.get("argument")),
                "attack_text": render_argument_text(turn.get("argument")),
            }
        )
    return out


def build_prompt(question: str, item: dict[str, Any]) -> str:
    """判定者に渡すプロンプト。手法名・宣言された攻撃の種類・決着状態は含めない."""
    return PROMPT.format(
        question=question,
        target=item["target_text"],
        attack=item["attack_text"],
        declared=item["declared_statement"] or "(none declared)",
    )


def sample_items(
    paths: list[Path], methods: set[str], n: int, seed: int
) -> dict[str, list[tuple[Path, dict[str, Any], dict[str, Any]]]]:
    """手法ごとに、攻撃の発言から無作為に n 件（ログ、発言の順）."""
    pool: dict[str, list[tuple[Path, dict[str, Any], dict[str, Any]]]] = defaultdict(list)
    for path in paths:
        log = json.loads(path.read_text(encoding="utf-8"))
        method = str(log.get("method"))
        if method not in methods:
            continue
        for item in attack_turns(log):
            pool[method].append((path, log, item))
    rng = random.Random(seed)
    return {m: rng.sample(v, min(n, len(v))) for m, v in sorted(pool.items())}


def _judge(model_name: str, prompt: str) -> AttackJudgement:
    structured = ChatOpenAI(model=model_name).with_structured_output(AttackJudgement)
    result = structured.invoke(prompt)
    return result if isinstance(result, AttackJudgement) else AttackJudgement.model_validate(result)


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """手法ごとの、攻撃として成立している割合（neither でない）、種類の内訳、宣言された文の一致率、却下との関係."""
    summary: dict[str, Any] = {}
    for method in sorted({str(r["method"]) for r in rows}):
        judged = [r for r in rows if r["method"] == method and r["attack_kind"] is not None]
        kinds: dict[str, int] = defaultdict(int)
        for r in judged:
            kinds[r["attack_kind"]] += 1
        declared = [r for r in judged if r["declared_statement_present"] is not None]
        valid = [r for r in judged if r["attack_kind"] != "neither"]
        rej = [r for r in judged if r["rejected_by_implementation"]]
        kept = [r for r in judged if not r["rejected_by_implementation"]]
        by_type: dict[str, list[bool]] = defaultdict(list)
        for r in judged:
            by_type[str(r["type"])].append(r["attack_kind"] != "neither")
        summary[method] = {
            "n_judged": len(judged),
            "valid_attack_rate": round(len(valid) / len(judged), 4) if judged else None,
            "kind_share": {k: round(v / len(judged), 4) for k, v in sorted(kinds.items())} if judged else {},
            "declared_statement_present_rate": round(
                sum(bool(r["declared_statement_present"]) for r in declared) / len(declared), 4
            )
            if declared
            else None,
            "n_rejected_by_implementation": len(rej),
            "valid_rate_among_rejected": round(sum(r["attack_kind"] != "neither" for r in rej) / len(rej), 4)
            if rej
            else None,
            "valid_rate_among_accepted": round(sum(r["attack_kind"] != "neither" for r in kept) / len(kept), 4)
            if kept
            else None,
            "valid_rate_by_turn_type": {k: round(sum(v) / len(v), 4) for k, v in sorted(by_type.items())},
        }
    return summary


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--source", type=parse_source, required=True, help="<実験フォルダ>:<手法,手法>（例: logs/final:schema,no_schema）。"
    )
    parser.add_argument("--n", type=int, default=100, help="各手法から無作為に選ぶ攻撃の数。")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--model", default=None, help="評価モデル（既定: 環境変数 MODEL）。")
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()

    root, methods = args.source
    model_name = resolve_evaluator_model(args.model)
    paths = sorted(root.resolve().glob("turns*/raw_dialogue/*/*/*.json"))
    sampled = sample_items(paths, set(methods), args.n, args.seed)
    total = sum(len(v) for v in sampled.values())
    print(f"{total} 件の攻撃を判定（{model_name}, 各手法 最大 {args.n} 件, seed={args.seed}）", flush=True)

    rows: list[dict[str, Any]] = []
    lock = threading.Lock()

    def run(method: str, path: Path, log: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
        base = {
            "method": method,
            "file": path.name,
            "topic": path.parent.name,
            "turns_setting": path.parents[3].name,
            "turn": item["turn"],
            "agent": item["agent"],
            "type": item["type"],
            "declared_attack": item["declared_attack"],
            "declared_statement": item["declared_statement"],
            "rejected_by_implementation": item["rejected_by_implementation"],
            "target_text": item["target_text"],
            "attack_text": item["attack_text"],
        }
        try:
            judgement = _judge(model_name, build_prompt(str(log.get("question", "")), item))
        except Exception as exc:  # noqa: BLE001 - 1 件の失敗で全体を止めない
            print(f"failed: {path.name} turn {item['turn']}: {exc}", flush=True)
            return {**base, "attack_kind": None, "declared_statement_present": None, "reason": f"failed: {exc}"}
        return {**base, **judgement.model_dump()}

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(run, m, p, lg, it) for m, items in sampled.items() for p, lg, it in items]
        for done, future in enumerate(as_completed(futures), start=1):
            with lock:
                rows.append(future.result())
                if done % 20 == 0 or done == total:
                    print(f"[{done:03d}/{total}]", flush=True)

    rows.sort(key=lambda r: (r["method"], r["turns_setting"], r["topic"], r["file"], r["turn"]))
    out = root / "eval_result" / "attack_validity" / "attack_validity.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps({"seed": args.seed, "n_per_method": args.n, "summary": summarize(rows), "detail": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Saved: {out}")
    for method, agg in summarize(rows).items():
        print(f"  {method:<10} {json.dumps(agg, ensure_ascii=False)}")


if __name__ == "__main__":
    main()
