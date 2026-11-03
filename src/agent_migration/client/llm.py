from abc import ABC, abstractmethod
from typing import Any

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, SecretStr


def _messages(prompt: str, system: str | None) -> Any:
    """system があれば、(system, user) のメッセージ列。なければ、prompt をそのまま渡す。"""
    return [("system", system), ("user", prompt)] if system else prompt


class LLMClient(ABC):
    @abstractmethod
    def chat(self, prompt: str, system: str | None = None) -> Any:
        raise NotImplementedError

    def structured(
        self, prompt: str, schema: type[BaseModel], system: str | None = None
    ) -> Any:
        raise NotImplementedError


class OpenAIClient(LLMClient):
    def __init__(
        self,
        model: str,
        api_key: SecretStr,
        callbacks: list[Any] | None = None,  # トークン数の集計など
    ):  # クライアントはmainからDIしない
        self.model = model
        self.client = ChatOpenAI(model=model, api_key=api_key, callbacks=callbacks)

    def chat(self, prompt: str, system: str | None = None) -> Any:
        response = self.client.ainvoke(_messages(prompt, system))
        return response

    def structured(
        self, prompt: str, schema: type[BaseModel], system: str | None = None
    ) -> Any:
        response = self.client.with_structured_output(
            schema=schema,
        ).ainvoke(_messages(prompt, system))
        return response
