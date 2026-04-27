"""New LangGraph Agent."""

__all__ = ["graph"]


def __getattr__(name: str):
    if name != "graph":
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    try:
        from .graph import graph
    except ImportError:  # pragma: no cover - supports template package loading.
        from agent.graph import graph
    return graph
