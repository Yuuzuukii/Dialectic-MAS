from typing import Any

from pydantic import BaseModel

from src.agent_migration.client.llm import LLMClient


class Agent:
    def __init__(self, client: LLMClient, system_prompt: str):
        self.system_prompt = system_prompt
        self.client = client

    def chat(self, prompt: str) -> Any:
        response = self.client.chat(prompt)
        return response

    def structured(self, prompt: str, schema: type[BaseModel]) -> Any:
        response = self.client.structured(prompt, schema)
        return response
