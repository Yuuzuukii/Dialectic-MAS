"""Dialect-MAS agent package."""

__all__ = ["graph"]


def __getattr__(name: str):
    if name != "graph":
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from .workflow import graph
    return graph
