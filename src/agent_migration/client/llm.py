from abc import ABC, abstractmethod
from typing import Any

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, SecretStr


class LLMClient(ABC):
    @abstractmethod
    def chat(self, prompt: str) -> Any:
        raise NotImplementedError

    def structured(self, prompt: str, schema: type[BaseModel]) -> Any:
        raise NotImplementedError


class OpenAIClient(LLMClient):
    def __init__(
        self, model: str, api_key: SecretStr
    ):  # クライアントはmainからDIしない
        self.model = model
        self.client = ChatOpenAI(model=model, api_key=api_key)

    def chat(self, prompt: str) -> Any:
        response = self.client.ainvoke(prompt)
        return response

    def structured(self, prompt: str, schema: type[BaseModel]) -> Any:
        response = self.client.with_structured_output(
            schema=schema,
        ).ainvoke(prompt)
        return response
