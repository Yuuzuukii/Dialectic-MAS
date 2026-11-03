from typing import Any

from pydantic import BaseModel

from src.agent_migration.client.llm import LLMClient


class Agent:
    def __init__(self, client: LLMClient, system_prompt: str):
        self.system_prompt = system_prompt
        self.client = client

    def chat(self, prompt: str, system: str | None = None) -> Any:
        response = self.client.chat(prompt, system=system)
        return response

    def structured(
        self, prompt: str, schema: type[BaseModel], system: str | None = None
    ) -> Any:
        response = self.client.structured(prompt, schema, system=system)
        return response
