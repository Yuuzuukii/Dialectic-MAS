"""LLM 呼び出しラッパ。`with_structured_output` による構造化出力と対話ログ記録を担う."""

import os
from typing import Any, Type, TypeVar, cast

from dotenv import load_dotenv
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai.chat_models import ChatOpenAI
from pydantic import BaseModel, SecretStr

try:
    from . import conversation_log
except ImportError:  # pragma: no cover - supports LangGraph file-path loading.
    import conversation_log  # type: ignore

load_dotenv()

T = TypeVar("T", bound=BaseModel)


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


def _structured_content(response: Any) -> Any:
    if isinstance(response, BaseModel):
        return response.model_dump(exclude_none=True)
    return response


async def call_llm_structured(prompt: str, schema: Type[T], model: str) -> T:
    """単一プロンプトを送り、schema に従った構造化出力を得る."""
    model_client = _chat_openai(model)
    structured_model = model_client.with_structured_output(schema)
    response = await structured_model.ainvoke(prompt)
    conversation_log.record(
        [HumanMessage(content=prompt)], _structured_content(response), model=model
    )
    return cast(T, response)


async def call_llm_messages_structured(messages: list[BaseMessage], schema: Type[T], model: str) -> T:
    """メッセージ列を送り、schema に従った構造化出力を得る."""
    model_client = _chat_openai(model)
    structured_model = model_client.with_structured_output(schema)
    response = await structured_model.ainvoke(messages)
    conversation_log.record(messages, _structured_content(response), model=model)
    return cast(T, response)


async def invoke_agent_structured(
    system_prompt: str,
    human_prompt: str,
    schema: Type[T],
    model: str | None = None,
) -> T:
    """System + human の2メッセージで構造化出力を得る."""
    return await call_llm_messages_structured(
        [SystemMessage(content=system_prompt), HumanMessage(content=human_prompt)],
        schema,
        model or os.getenv("MODEL") or "gpt-5-mini",
    )


async def invoke_agent_structured_messages(
    messages: list[BaseMessage],
    schema: Type[T],
    model: str | None = None,
) -> T:
    """任意のメッセージ列（system + 履歴 + 指示）で構造化出力を得る."""
    return await call_llm_messages_structured(
        messages,
        schema,
        model or os.getenv("MODEL") or "gpt-5-mini",
    )


async def call_llm(prompt: str, model: str, config: RunnableConfig | None = None) -> str:
    """単一プロンプトを送り、応答テキストを返す（構造化なし）."""
    model_client = _chat_openai(model)
    response = await model_client.ainvoke(prompt, config=config)
    text = _message_content_to_text(response)
    conversation_log.record([HumanMessage(content=prompt)], text, model=model)
    return text


async def call_llm_messages(messages: list[BaseMessage], model: str, temperature: float | None = 0.7) -> str:
    """メッセージ列を送り、応答テキストを返す（構造化なし）."""
    model_client = _chat_openai(model, temperature=temperature)
    response = await model_client.ainvoke(messages)
    text = _message_content_to_text(response)
    conversation_log.record(messages, text, model=model)
    return text
