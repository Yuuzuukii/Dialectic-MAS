import asyncio

from src.agent_migration.agents import Agent
from src.agent_migration.argumentation.dialectical import DialecticalProtocol
from src.agent_migration.argumentation.no_schema import NoSchemaProtocol
from src.agent_migration.client.llm import OpenAIClient
from src.agent_migration.config import (
    DIALOGUE_AGENT_MODEL,
    JUDGE_MODEL,
    OPENAI_API_KEY,
)

openAIClient = OpenAIClient(model=DIALOGUE_AGENT_MODEL, api_key=OPENAI_API_KEY)
judgeClient = OpenAIClient(model=JUDGE_MODEL, api_key=OPENAI_API_KEY)
ag1 = Agent(client=openAIClient, system_prompt="")
ag2 = Agent(client=openAIClient, system_prompt="")
judge = Agent(client=judgeClient, system_prompt="")  # no schema 版の判定用（NoSchemaProtocol で使う）

# 論題と、各エージェントの theory（stance）は、実験側から渡す。ここは仮。
dialogue = DialecticalProtocol(
    ag1=ag1,
    ag2=ag2,
    issue="topic",
    theory1="theory of agent 1",
    theory2="theory of agent 2",
    max_turns=10,
)
# no schema 版（スキーマ指示なし）: NoSchemaProtocol(..., max_turns=10, judge=judge)

if __name__ == "__main__":
    result = asyncio.run(dialogue.run())
    print(result.final_answer)
