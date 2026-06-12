"""AIMessage の `name` がエージェント識別にどれだけ効くかを測る実験スクリプト。

LangChain は `AIMessage(content=..., name="ag1")` を OpenAI へ
`{"role": "assistant", "name": "ag1", "content": ...}` として送る
（このスクリプトの `--show-payload` で確認できる）。
問題は「モデルがその `name` を読んで “どの発言が誰のものか” を区別しているか」。

それを切り分けるため、各エージェントに別々の「秘密番号」を履歴の AIMessage で
言わせ、システムプロンプトで「あなたは ag1」と名乗らせたうえで
「あなた自身の秘密番号は？」と訊く。正解できるのは、過去の assistant 発言の
うち “自分のもの” を識別できた場合だけ。

4条件で比較する:
  name_only   : AIMessage に name を付与。content には誰の発言か書かない（= name の純粋な効果）
  label_only  : name を付けず、content に「[ag1] ...」と明示（テキストラベルの効果＝上限）
  both        : name とラベルの両方
  none        : どちらも無し（識別不能なので ~50% がチャンスレベル＝下限）

各条件を N 試行（秘密番号の割当と発言順をランダム化）して正答率を出す。

使い方:
  PYTHONPATH=src .venv/bin/python scripts/test_aimessage_name.py
  PYTHONPATH=src .venv/bin/python scripts/test_aimessage_name.py --model gpt-4o --trials 12
  PYTHONPATH=src .venv/bin/python scripts/test_aimessage_name.py --show-payload
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

# PYTHONPATH=src を付け忘れても import できるようにする保険。
_SRC = os.path.join(os.path.dirname(__file__), "..", "src")
if os.path.isdir(_SRC) and _SRC not in sys.path:
    sys.path.insert(0, _SRC)

# プロジェクトの API キー処理・gpt-5 温度除外をそのまま使う。
from agent.llm import _chat_openai  # noqa: E402

CONDITIONS = ("name_only", "label_only", "both", "none")


class SecretAnswer(BaseModel):
    """構造化出力。自分の秘密番号と、その判断理由。"""

    secret_number: int = Field(description="あなた自身（指定されたエージェント）の秘密番号")
    reasoning: str = Field(description="どの発言を自分のものと判断したか、一言で")


def _agent_message(condition: str, agent_id: str, secret: int) -> AIMessage:
    """1エージェントの過去発言を、条件に応じて組み立てる。"""
    bare = f"私の秘密番号は {secret} です。この番号で議論を続けます。"
    labeled = f"[{agent_id}] {bare}"

    if condition == "name_only":
        return AIMessage(content=bare, name=agent_id)
    if condition == "label_only":
        return AIMessage(content=labeled)
    if condition == "both":
        return AIMessage(content=labeled, name=agent_id)
    if condition == "none":
        return AIMessage(content=bare)
    raise ValueError(f"unknown condition: {condition}")


def build_messages(
    condition: str, self_id: str, other_id: str, self_secret: int, other_secret: int, self_first: bool
) -> list[BaseMessage]:
    """system → 履歴(2発言) → 指示 の順でメッセージ列を作る。"""
    system = SystemMessage(
        content=(
            f"あなたはエージェント {self_id} です。{other_id} と議論しています。"
            "以下にこれまでの対話履歴（assistant 発言）が含まれます。"
        )
    )
    self_msg = _agent_message(condition, self_id, self_secret)
    other_msg = _agent_message(condition, other_id, other_secret)
    history = [self_msg, other_msg] if self_first else [other_msg, self_msg]

    instruction = HumanMessage(
        content=(
            f"あなた自身（{self_id}）が先ほど宣言した秘密番号を答えてください。"
            f"{other_id} の番号ではなく、{self_id} 自身の番号です。"
        )
    )
    return [system, *history, instruction]


def _to_openai_dict(message: BaseMessage) -> dict[str, Any]:
    """送ったメッセージを OpenAI 形式（role/name/content）に変換してログ用に返す。"""
    from langchain_openai.chat_models.base import _convert_message_to_dict

    return _convert_message_to_dict(message)


async def run_trial(condition: str, model: str, index: int) -> dict[str, Any]:
    """1試行。割当と順序をランダム化して実行し、送受信を含むログ用 dict を返す。"""
    self_id, other_id = "ag1", "ag2"
    self_secret = random.randint(10, 99)
    other_secret = random.randint(10, 99)
    while other_secret == self_secret:
        other_secret = random.randint(10, 99)
    self_first = random.random() < 0.5

    messages = build_messages(condition, self_id, other_id, self_secret, other_secret, self_first)
    client = _chat_openai(model).with_structured_output(SecretAnswer)
    answer = cast(SecretAnswer, await client.ainvoke(messages))
    ok = answer.secret_number == self_secret

    return {
        "condition": condition,
        "trial": index,
        "model": model,
        "correct": ok,
        "ground_truth": {
            "self_id": self_id,
            "self_secret": self_secret,
            "other_secret": other_secret,
            "self_first": self_first,
        },
        "request": [_to_openai_dict(m) for m in messages],
        "response": answer.model_dump(),
    }


async def run_condition(condition: str, model: str, trials: int) -> tuple[float, list[dict[str, Any]]]:
    records = await asyncio.gather(
        *(run_trial(condition, model, i) for i in range(trials))
    )
    correct = sum(1 for r in records if r["correct"])
    print(f"\n[{condition}]  正答率 {correct}/{trials} = {correct / trials:.0%}")
    for r in records:
        mark = "✓" if r["correct"] else "✗"
        ans, truth = r["response"]["secret_number"], r["ground_truth"]["self_secret"]
        print(f"   {mark} 回答={ans:2d} 正解={truth:2d}  理由: {r['response']['reasoning'][:60]}")
    return correct / trials, list(records)


def show_payload() -> None:
    """LangChain が name をどう OpenAI 形式へ変換するか確認する。"""
    from langchain_openai.chat_models.base import _convert_message_to_dict

    print("=== LangChain → OpenAI 変換の確認 ===")
    for cond in CONDITIONS:
        msg = _agent_message(cond, "ag1", 42)
        print(f"[{cond:11s}] {_convert_message_to_dict(msg)}")
    print()


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=os.getenv("MODEL", "gpt-5-mini"))
    parser.add_argument("--trials", type=int, default=8, help="条件ごとの試行回数")
    parser.add_argument(
        "--conditions", nargs="+", default=list(CONDITIONS), choices=CONDITIONS
    )
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--show-payload", action="store_true", help="OpenAI 送信形式を表示して終了"
    )
    parser.add_argument(
        "--log-dir",
        default=str(Path(__file__).resolve().parent.parent / "logs" / "aimessage_name"),
        help="送受信ログ（JSON）の出力先ディレクトリ",
    )
    args = parser.parse_args()

    show_payload()
    if args.show_payload:
        return

    random.seed(args.seed)
    print(f"model={args.model}  trials/condition={args.trials}\n")
    print("解釈: name_only が none より明確に高ければ、モデルは `name` を識別に使っている。")
    print("      name_only が label_only に近いほど、name はテキストラベル並みに効いている。")

    summary = {}
    all_records: list[dict[str, Any]] = []
    for cond in args.conditions:
        rate, records = await run_condition(cond, args.model, args.trials)
        summary[cond] = rate
        all_records.extend(records)

    print("\n=== まとめ ===")
    for cond in args.conditions:
        print(f"  {cond:11s} {summary[cond]:.0%}")

    # 送受信ログを JSON で残す。
    log_dir = Path(args.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = log_dir / f"{args.model}_{stamp}.json"
    log_path.write_text(
        json.dumps(
            {
                "model": args.model,
                "trials_per_condition": args.trials,
                "seed": args.seed,
                "summary": summary,
                "records": all_records,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nログを書き出しました: {log_path}")


if __name__ == "__main__":
    asyncio.run(main())
