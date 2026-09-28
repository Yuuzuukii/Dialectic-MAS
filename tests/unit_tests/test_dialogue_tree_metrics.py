"""experiments/dialogue/common.py の dialogue tree 深さ再構築（_reconstruct_depths）と
_dialogue_tree_metrics のテスト.

`State.dialogue_nodes` はラウンドが変わるたびリセットされる一時状態なので、
debate 全体を通じて一度も消えない `dialogue_history`（type + target_id）だけから
深さを再計算できることを確認する。
"""

from __future__ import annotations

import pytest

from experiments.dialogue.common import _dialogue_tree_metrics, _reconstruct_depths

pytestmark = pytest.mark.anyio


def _turn(id_: str, type_: str, target_id: str | None = None, **extra: object) -> dict:
    return {"id": id_, "type": type_, "target_id": target_id, "argument": "{}", **extra}


async def test_depth_stays_zero_without_a_promoted_counter() -> None:
    """B が A を defeat、C が B に応答するが、C を標的にする次の攻撃が無い
    （＝strictly defeat が成立しなかった）場合、depth は全て 0 のまま."""
    history = [
        _turn("A", "main"),
        _turn("B", "defeat", target_id="A"),
        _turn("C1", "counter", target_id="B"),
        _turn("C2", "counter", target_id="B"),  # 同じBへのリトライ
    ]

    depths = _reconstruct_depths(history)

    assert depths == {"A": 0, "B": 0, "C1": 0, "C2": 0}


async def test_depth_increases_when_a_counter_is_promoted_to_a_new_frame() -> None:
    """C が B を strictly defeat すると、C を標的にする次の defeat (D) は depth+1
    （実際のパイロットログ schema_20260915_175638_780894.json で観測されたパターン）。"""
    history = [
        _turn("A", "main"),
        _turn("B", "defeat", target_id="A"),
        _turn("C1", "counter", target_id="B"),  # 失敗（リトライされる）
        _turn("C2", "counter", target_id="B"),  # 成功（strictly defeat）→ 新フレーム
        _turn("D", "defeat", target_id="C2"),  # 新フレーム(depth1)への攻撃
    ]

    depths = _reconstruct_depths(history)

    assert depths["A"] == 0
    assert depths["B"] == 0
    assert depths["C1"] == 0
    assert depths["C2"] == 0
    assert depths["D"] == 1


async def test_undercut_blocker_stays_at_the_same_depth_as_what_it_blocks() -> None:
    """rebut を防ぐ undercut ブロッカー（type は常に "defeat"）は、ブロック対象の
    defeat と同じフレーム＝同じ depth として扱う（新フレームへ昇格させない）。"""
    history = [
        _turn("A", "main"),
        _turn("B", "defeat", target_id="A"),
        _turn("C", "counter", target_id="B"),  # C が B を strictly defeat（新フレーム）
        _turn("D", "defeat", target_id="C"),  # depth1 の C への rebut
        _turn("E", "defeat", target_id="D"),  # D を防ぐ undercut ブロッカー
    ]

    depths = _reconstruct_depths(history)

    assert depths["D"] == 1
    assert depths["E"] == 1  # D と同じフレーム（ブロック対象と同深さ）


async def test_dialogue_tree_metrics_reports_depth_and_frame_count_from_two_threads() -> None:
    """AG1/AG2 両方のスレッドを通じた累計の frame 数・最大深さが正しく出る
    （dialogue_nodes に依存せず dialogue_history だけから計算される）。"""
    dialogue_history = [
        _turn("A1", "main", status="defensible", closed_by_budget=True),
        _turn("B1", "defeat", target_id="A1"),
        _turn("C1", "counter", target_id="B1"),
        _turn("D1", "defeat", target_id="C1"),  # AG1側で depth1 まで到達
        _turn("A2", "main", status="justified", closed_by_budget=False),
        _turn("B2", "defeat", target_id="A2"),
    ]
    final_state = {"dialogue_history": dialogue_history, "dialogue_nodes": []}

    metrics = _dialogue_tree_metrics(final_state)

    assert metrics["dialogue_tree_max_depth"] == 1
    # frame数 = main 2本 + 昇格した counter 1本（C1）
    assert metrics["dialogue_tree_node_count"] == 3
    assert metrics["main_argument_count"] == 2
    assert metrics["justified_proven_count"] == 1
    assert metrics["justified_by_budget_count"] == 0
    assert metrics["defensible_count"] == 1
