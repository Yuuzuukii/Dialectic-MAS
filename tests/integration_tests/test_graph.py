import pytest

from agent import graph

pytestmark = pytest.mark.anyio


async def test_agent_graph_compiles() -> None:
    assert graph is not None
