"""Dialect-MAS agent package."""

from typing import Any

__all__ = ["graph"]


def __getattr__(name: str) -> Any:
    if name != "graph":
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from .workflow import graph
    return graph
