"""エージェント呼び出しを role/content 形式で記録するための軽量レコーダ。

各 LLM 呼び出しの入力メッセージ（system / user）とモデル応答（assistant）を
role/content の組として収集し、cli.py から JSON にダンプするために使う。
プロセス内のグローバルなバッファに溜め、`reset()` で記録開始、`dump()` で書き出す。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from langchain_core.messages import BaseMessage

# LangChain のメッセージ種別 -> OpenAI 互換の role
_ROLE_MAP = {"system": "system", "human": "user", "ai": "assistant", "tool": "tool"}

_records: list[dict[str, Any]] = []
_enabled = False


def reset() -> None:
    """記録を有効化し、バッファを空にする。実行開始時に呼ぶ。"""
    global _records, _enabled
    _records = []
    _enabled = True


def is_enabled() -> bool:
    return _enabled


def _role_of(message: BaseMessage) -> str:
    msg_type = getattr(message, "type", "")
    return _ROLE_MAP.get(msg_type, msg_type or "unknown")


def _content_of(message: BaseMessage) -> Any:
    content = message.content
    if isinstance(content, str):
        return content
    return [str(part) for part in content]


def record(messages: list[BaseMessage], response_content: Any, *, model: str) -> None:
    """1回の LLM 呼び出しを role/content 形式で記録する。

    messages: 送信した入力メッセージ列（system / user）。
    response_content: モデル応答の中身（テキスト or 構造化出力の dict）。assistant として記録する。
    """
    if not _enabled:
        return
    _records.append(
        {
            "index": len(_records),
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "model": model,
            "messages": [
                {"role": _role_of(message), "content": _content_of(message)}
                for message in messages
            ],
            "response": {"role": "assistant", "content": response_content},
        }
    )


def records() -> list[dict[str, Any]]:
    return _records


def dump(path: str | Path, metadata: dict[str, Any] | None = None) -> Path:
    """記録した全 exchange を JSON で書き出す。親ディレクトリは自動生成する。"""
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {**(metadata or {}), "exchanges": _records}
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return out_path
