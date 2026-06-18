"""エージェントが AIMessage の `name` から自分の発話を識別できるかの簡易テスト.

ag1 と ag2 が同じ議題について自然に相談している履歴を与え、
ag1 に「あなた自身が提案したものは？」と尋ねて、ag1 自身の発話（name="ag1"）を
正しく参照できるかを確認する。

実行方法:
    cd src && python test_name_identity.py
"""

import asyncio
import os

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai.chat_models import ChatOpenAI
from pydantic import SecretStr

load_dotenv()

MODEL = "gpt-5-mini"


async def main() -> None:
    api_key = os.getenv("OPENAI_API_KEY")
    if api_key is None:
        raise ValueError("OPENAI_API_KEY environment variable is not set")

    llm = ChatOpenAI(model=MODEL, api_key=SecretStr(api_key))

    # 対話は自然に見えるが、両者が同じ種類の「案」を出しているため、
    # ag1 自身の案だけを答えるには AIMessage の `name` フィールドを参照する必要がある。
    messages = [
        SystemMessage(
            content=("あなたは ag1 です。ag2 とイベント企画について対話しています。")
        ),
        HumanMessage(content="来月の社内交流会について、二人で案を出してください。"),
        AIMessage(
            content=(
                "まず会場は駅近の小さなカフェを借りるのがよいと思います。"
                "移動の負担が少ないので、参加率を上げやすいはずです。"
            ),
            name="ag1",
        ),
        AIMessage(
            content=(
                "私は会社のラウンジを使う案を推します。"
                "費用を抑えられますし、準備と片付けも短時間で済みます。"
            ),
            name="ag2",
        ),
        HumanMessage(content="当日の最初の企画はどうしましょうか。"),
        AIMessage(
            content=(
                "最初は三人組で最近取り組んだ仕事を一つずつ紹介する時間にしたいです。"
                "雑談だけより、初対面でも話し始めやすくなります。"
            ),
            name="ag1",
        ),
        AIMessage(
            content=(
                "私は部署をまたいだクイズを最初に置くのがよいと思います。"
                "短時間で場が温まり、人数が多くても進行しやすいです。"
            ),
            name="ag2",
        ),
        HumanMessage(content="最後に、参加者へ渡すものも決めておきたいです。"),
        AIMessage(
            content=(
                "参加者には、次に話してみたい人の名前を書ける小さなカードを渡しましょう。"
                "交流会の後にもつながりを残せます。"
            ),
            name="ag1",
        ),
        AIMessage(
            content=(
                "私は各部署のおすすめツールをまとめた一枚資料を渡すのがよいと思います。"
                "交流会で出た話を業務にも持ち帰りやすくなります。"
            ),
            name="ag2",
        ),
        HumanMessage(
            content=(
                "あなた自身がこの会話で提案した、会場案、最初の企画、"
                "参加者へ渡すものをそれぞれ答えてください。"
            )
        ),
    ]

    response = await llm.ainvoke(messages)

    print("=== messages ===")
    for m in messages:
        name = getattr(m, "name", None)
        print(f"[{m.type}] name={name!r}: {m.content}")

    print("\n=== response (ag1) ===")
    print(response.content)


if __name__ == "__main__":
    asyncio.run(main())
