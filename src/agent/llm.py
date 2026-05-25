import os

from typing import Optional, Type, TypeVar, cast

from dotenv import load_dotenv
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_openai.chat_models import ChatOpenAI
from pydantic import BaseModel, SecretStr

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


def _chat_openai(model: str, temperature: Optional[float] = None) -> ChatOpenAI:
    kwargs = {
        "model": model,
        "api_key": _openai_api_key(),
    }
    if temperature is not None and not model.lower().startswith("gpt-5"):
        kwargs["temperature"] = temperature
    return ChatOpenAI(**kwargs)


async def call_llm_structured(prompt: str, schema: Type[T], model: str) -> T:
    model_client = _chat_openai(model)
    structured_model = model_client.with_structured_output(schema)
    response = await structured_model.ainvoke(prompt)
    return cast(T, response)


async def call_llm_messages_structured(messages: list[BaseMessage], schema: Type[T], model: str) -> T:
    model_client = _chat_openai(model)
    structured_model = model_client.with_structured_output(schema)
    response = await structured_model.ainvoke(messages)
    return cast(T, response)


async def invoke_agent_structured(
    system_prompt: str,
    human_prompt: str,
    schema: Type[T],
    model: str | None = None,
) -> T:
    return await call_llm_messages_structured(
        [SystemMessage(content=system_prompt), HumanMessage(content=human_prompt)],
        schema,
        model or os.getenv("MODEL", "gpt-5-mini"),
    )


async def call_llm(prompt: str, model: str) -> str:
    model_client = _chat_openai(model)
    response = await model_client.ainvoke(prompt)
    return _message_content_to_text(response)


async def call_llm_messages(messages: list[BaseMessage], model: str, temperature: Optional[float] = 0.7) -> str:
    model_client = _chat_openai(model, temperature=temperature)
    response = await model_client.ainvoke(messages)
    return _message_content_to_text(response)
