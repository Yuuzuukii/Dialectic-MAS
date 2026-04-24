"""New LangGraph Agent.

This module defines a custom graph.
"""

try:
    from .graph import graph
except ImportError:  # pragma: no cover - supports template package loading.
    from agent.graph import graph

__all__ = ["graph"]
