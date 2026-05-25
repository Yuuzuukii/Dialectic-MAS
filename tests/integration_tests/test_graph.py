import pytest

from agent import graph
from agent.graphs.dialectic_workflow import graph as compiled_graph

pytestmark = pytest.mark.anyio


async def test_agent_graph_compiles() -> None:
    assert graph is not None
    assert graph is compiled_graph


async def test_agent_graph_uses_abc_flow_without_d_nodes() -> None:
    nodes = set(compiled_graph.get_graph().nodes)

    assert {
        "can_generate_main",
        "validate_b_defeats_a",
        "validate_c_defeats_b",
        "validate_b_defeats_c",
    } <= nodes
    assert "p_main" not in nodes
    assert "initialize" not in nodes
    assert "o_defeat_c" not in nodes
    assert "p_undercut_d" not in nodes
