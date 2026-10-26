import asyncio

from src.agent_migration.agents import Agent
from src.agent_migration.argumentation.dialectical import (
    DEFAULT_SCHEMA,
    DialecticalArgument,
)
from src.agent_migration.client.llm import OpenAIClient
from src.agent_migration.config import (
    DIALOGUE_AGENT_MODEL,
    JUDGE_MODEL,
    OPENAI_API_KEY,
)

openAIClient = OpenAIClient(model=DIALOGUE_AGENT_MODEL, api_key=OPENAI_API_KEY)
judgeClient = OpenAIClient(model=JUDGE_MODEL, api_key=OPENAI_API_KEY)
ag1 = Agent(client=openAIClient, system_prompt="a")
ag2 = Agent(client=openAIClient, system_prompt="a")
judge = Agent(client=judgeClient, system_prompt="")


dialogue = DialecticalArgument(
    ag1=ag1,
    ag2=ag2,
    topic="topic",
    schema=DEFAULT_SCHEMA,  # None にすると no_schema（Argument 本体が自由記述）
    max_turn=10,
    judge=judge,
)

if __name__ == "__main__":
    result = asyncio.run(dialogue.run())
    print(result["final_answer"])
