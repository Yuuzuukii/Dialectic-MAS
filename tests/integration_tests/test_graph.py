import pytest

from agent import graph
from agent.workflow import graph as compiled_graph

pytestmark = pytest.mark.anyio


async def test_agent_graph_compiles() -> None:
    assert graph is not None
    assert graph is compiled_graph


async def test_agent_graph_uses_recursive_dialogue_tree_nodes() -> None:
    """A-B-C の固定シナリオではなく、dialogue tree（Prakken & Sartor Definition 4.6）を
    explicit stack で再帰的に探索するノード構成になっていることを確認する。
    opponent_move/proponent_move はスタック上の任意の深さのフレームに対して働くため、
    C 以降（D, E, ...）への攻撃も同じノードの再訪問で表現され、固定ノードは増えない。
    """
    nodes = set(compiled_graph.get_graph().nodes)

    assert {
        "can_generate_main",
        "init_dialogue_tree",
        "opponent_move",
        "validate_opponent_move",
        "proponent_move",
        "validate_proponent_move",
        "pop_and_propagate",
        "resolve_tree_status",
    } <= nodes
    # 旧 A-B-C 固定フロー由来のノード名は存在しない。
    assert "o_defeat_a" not in nodes
    assert "p_counter_b" not in nodes
    assert "validate_b_defeats_a" not in nodes
    assert "validate_c_defeats_b" not in nodes
    assert "validate_b_defeats_c" not in nodes
    # D 以降専用の固定ノードも作らない（同じノードの再訪問で任意深さを表現するため）。
    assert "o_defeat_c" not in nodes
    assert "p_undercut_d" not in nodes
