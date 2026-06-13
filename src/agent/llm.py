"""LLM 呼び出しラッパ。`with_structured_output` による構造化出力と素のテキスト出力を担う."""

import os
from typing import Any, Type, TypeVar, cast

from dotenv import load_dotenv
from langchain_core.messages import BaseMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai.chat_models import ChatOpenAI
from pydantic import BaseModel, SecretStr

load_dotenv()

T = TypeVar("T", bound=BaseModel)

_DEFAULT_MODEL = "gpt-5-mini"


def _model_name(model: str | None) -> str:
    return model or os.getenv("MODEL") or _DEFAULT_MODEL


def _openai_api_key() -> SecretStr:
    raw_key = os.getenv("OPENAI_API_KEY")
    if raw_key is None:
        raise ValueError("OPENAI_API_KEY environment variable is not set")
    return SecretStr(raw_key)


def _message_content_to_text(message: BaseMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    return "\n".join(str(part) for part in content)


def _chat_openai(model: str, temperature: float | None = None) -> ChatOpenAI:
    kwargs: dict[str, Any] = {
        "model": model,
        "api_key": _openai_api_key(),
    }
    if temperature is not None and not model.lower().startswith("gpt-5"):
        kwargs["temperature"] = temperature
    return ChatOpenAI(**kwargs)


async def chat_structured(
    messages: list[BaseMessage], schema: Type[T], *, model: str | None = None
) -> T:
    """メッセージ列を送り、schema に従った構造化出力を得る."""
    model_client = _chat_openai(_model_name(model))
    structured_model = model_client.with_structured_output(schema)
    response = await structured_model.ainvoke(messages)
    return cast(T, response)


async def chat_text(
    messages: list[BaseMessage],
    *,
    model: str | None = None,
    temperature: float | None = None,
    config: RunnableConfig | None = None,
) -> str:
    """メッセージ列を送り、応答テキストを返す（構造化なし）."""
    model_client = _chat_openai(_model_name(model), temperature=temperature)
    response = await model_client.ainvoke(messages, config=config)
    return _message_content_to_text(response)
