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

_DEFAULT_MODEL = "gpt-5.4-mini"

# GPT-5 系は temperature ではなく reasoning_effort / verbosity で挙動を制御する
# （CLAUDE.md の GPT-5 Prompting Guide 参照）。従来はどちらも未設定＝API 既定 medium
# のままで、schema の構造化タスクは制約充足に推論予算を食われていた。ここで全手法・
# 全呼び出しに一律で効く既定値を 1 つ用意し（REASONING_EFFORT で上書き可）、手法間の
# 公平性を保ったまま推論予算を明示的に与える。
_DEFAULT_REASONING_EFFORT = os.getenv("REASONING_EFFORT", "high")


def _model_name(model: str | None) -> str:
    return model or os.getenv("MODEL") or _DEFAULT_MODEL


def _is_gpt5(model: str) -> bool:
    return model.lower().startswith("gpt-5")


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


def _chat_openai(
    model: str,
    temperature: float | None = None,
    reasoning_effort: str | None = None,
    verbosity: str | None = None,
) -> ChatOpenAI:
    kwargs: dict[str, Any] = {
        "model": model,
        "api_key": _openai_api_key(),
    }
    if _is_gpt5(model):
        # GPT-5 系: temperature は使わず reasoning_effort / verbosity で制御。
        # reasoning_effort は明示指定が無ければ全呼び出し共通の既定値を必ず与える。
        kwargs["reasoning_effort"] = reasoning_effort or _DEFAULT_REASONING_EFFORT
        if verbosity is not None:
            kwargs["verbosity"] = verbosity
    elif temperature is not None:
        kwargs["temperature"] = temperature
    return ChatOpenAI(**kwargs)


async def chat_structured(
    messages: list[BaseMessage],
    schema: Type[T],
    *,
    model: str | None = None,
    reasoning_effort: str | None = None,
) -> T:
    """メッセージ列を送り、schema に従った構造化出力を得る."""
    model_client = _chat_openai(
        _model_name(model), reasoning_effort=reasoning_effort
    )
    structured_model = model_client.with_structured_output(schema)
    response = await structured_model.ainvoke(messages)
    return cast(T, response)


async def chat_text(
    messages: list[BaseMessage],
    *,
    model: str | None = None,
    temperature: float | None = None,
    reasoning_effort: str | None = None,
    verbosity: str | None = None,
    config: RunnableConfig | None = None,
) -> str:
    """メッセージ列を送り、応答テキストを返す（構造化なし）."""
    model_client = _chat_openai(
        _model_name(model),
        temperature=temperature,
        reasoning_effort=reasoning_effort,
        verbosity=verbosity,
    )
    response = await model_client.ainvoke(messages, config=config)
    return _message_content_to_text(response)
