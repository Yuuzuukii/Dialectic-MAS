"""dialogue tree（Prakken & Sartor, Definition 4.5/4.6）の再帰探索の単体テスト.

`opponent_move` / `validate_opponent_move` / `proponent_move` /
`validate_proponent_move` / `pop_and_propagate` / `resolve_tree_status` を、
LLM 呼び出し（`generate_attack` / `evaluate_attack` / `ask_attack_extends`）を
モックしながら実際に駆動し、木の解決（AND/OR 集約）が原論文の定義どおりに
動くことを検証する。
"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

import pytest

from agent.argumentation_model import AttackEvaluation, AttackMatch
from agent.schema.state import ArgumentRecord
from agent.workflow import State

pytestmark = pytest.mark.anyio


def _record(agent: str, conc: str) -> ArgumentRecord:
    payload = {"Argument": {"rules": [], "Conc": [conc], "Ass": []}}
    return ArgumentRecord(
        type="main", argument=json.dumps(payload), support=[], agent=agent  # type: ignore[arg-type]
    )


def _fresh_state(main: ArgumentRecord) -> State:
    # can_generate_main を経由しない直接構築なので、ここで proponent を明示的に
    # 付ける（_dialogue_turn_budget_exceeded は ArgumentRecord.proponent で
    # カウントするため）。
    main = main.model_copy(update={"proponent": "AG1"})
    return State(
        question="Q?",
        agent1_stance="s1",
        agent2_stance="s2",
        current_argument=main,
        current_proponent="AG1",
        current_opponent="AG2",
        argument_records=[main],
    )


async def _run_tree(
    state: State,
    *,
    attacks: list[ArgumentRecord | None],
    counters: list[ArgumentRecord | None],
    defeats: list[bool],
    reverse_defeats: list[bool],
) -> State:
    """opponent_move/proponent_move が生成する論証と、その defeat 判定結果を
    あらかじめ用意したリストで順番に差し替えながら、木が解決するまで駆動する.

    - attacks: `generate_attack(purpose="defeat", ...)` の返り値を順に払い出す。
    - counters: `generate_attack(purpose="counter", ...)` の返り値を順に払い出す。
    - defeats: `evaluate_attack` の `defeats` を順に払い出す（B→target, C→B の両方で
      1つずつ消費される）。
    - reverse_defeats: `B が C に反撃できるか`（`evaluate_attack` の2回目呼び出し、
      B→C）の `defeats` を順に払い出す。extends は常に True として扱う。
    """
    attacks_iter = iter(attacks)
    counters_iter = iter(counters)
    defeats_iter = iter(defeats)
    reverse_iter = iter(reverse_defeats)

    async def fake_generate_attack(
        _state: Any, _agent: Any, _target: Any, *, purpose: str, attempt_count: int = 0
    ):
        if purpose == "defeat":
            return next(attacks_iter, None)
        return next(counters_iter, None)

    async def fake_ask_attack_extends(*_args, **_kwargs):
        # B-C 間で改めて宣言された攻撃関係（常に「及ぶ」ものとして rebut/Conc を返す。
        # 実際に defeat するかどうかは stage_aware_evaluate_attack 側の reverse_defeats で制御）。
        return AttackMatch(method="rebut", field="Conc", statement="c's conclusion")

    async def stage_aware_evaluate_attack(_state, attacker, target, _defender, **kwargs):
        # proponent_move 経由の「B defeats C」逆検証だけ persist_metadata=False で
        # 呼ばれるので、それを reverse_defeats、それ以外を defeats で消費する。
        if kwargs.get("persist_metadata") is False:
            return AttackEvaluation(
                defeats=next(reverse_iter), attack=attacker.attack or "rebut", relations=[]
            )
        return AttackEvaluation(
            defeats=next(defeats_iter), attack=attacker.attack or "rebut", relations=[]
        )

    def _apply(update: dict[str, Any]) -> None:
        nonlocal state
        state = replace(state, **update)

    import agent.nodes as nodes_module

    original_generate_attack = nodes_module.generate_attack
    original_evaluate_attack = nodes_module.evaluate_attack
    original_ask_attack_extends = nodes_module.ask_attack_extends

    nodes_module.generate_attack = fake_generate_attack  # type: ignore[assignment]
    nodes_module.ask_attack_extends = fake_ask_attack_extends  # type: ignore[assignment]

    nodes_module.evaluate_attack = stage_aware_evaluate_attack  # type: ignore[assignment]

    try:
        current = "init_dialogue_tree"
        for _ in range(200):  # 安全弁（無限ループ防止）
            fn = getattr(nodes_module, current)
            update = await fn(state)
            assert "error" not in update, update
            _apply(update)
            if current == "opponent_move":
                current = (
                    "validate_opponent_move"
                    if state.pending_attacker_argument is not None
                    else "pop_and_propagate"
                )
            elif current == "validate_opponent_move":
                current = "proponent_move" if state.last_attack_defeated else "opponent_move"
            elif current == "proponent_move":
                current = (
                    "validate_proponent_move"
                    if state.pending_counter_argument is not None
                    else "pop_and_propagate"
                )
            elif current == "validate_proponent_move":
                current = (
                    "opponent_move" if state.last_counter_strictly_defeated else "proponent_move"
                )
            elif current == "pop_and_propagate":
                if state.last_propagation_action == "resolved":
                    current = "resolve_tree_status"
                elif state.last_propagation_action == "retry_attack":
                    current = "opponent_move"
                else:
                    current = "pop_and_propagate"
            elif current == "init_dialogue_tree":
                current = "opponent_move"
            elif current == "resolve_tree_status":
                break
        else:
            raise AssertionError("dialogue tree did not resolve within 200 steps")
    finally:
        nodes_module.generate_attack = original_generate_attack
        nodes_module.evaluate_attack = original_evaluate_attack
        nodes_module.ask_attack_extends = original_ask_attack_extends

    return state


async def test_no_attack_available_is_justified() -> None:
    """O が A への攻撃を1つも生成できない ＝ 深さ0で即 justified."""
    main = _record("AG1", "we should choose a")
    state = _fresh_state(main)

    result = await _run_tree(
        state, attacks=[None], counters=[], defeats=[], reverse_defeats=[]
    )

    assert result.tree_root_status == "justified"
    assert result.tree_root_closed_by_budget is False


async def test_global_dialogue_turn_budget_is_defensible_not_justified() -> None:
    """max_dialogue_turns（対話全体の予算）が尽きて opponent_move が打ち切られた場合、
    won_by_p（→justified）にはせず undetermined（→defensible）にする。

    パイロット実行（logs/pilot_gpt54nano_turns10）で実際に観測された「ちょうど
    max_dialogue_turns に達した直後に justified になる」という、対象論証が本当に
    守り切れたかとは無関係な理由で justified 扱いになっていた問題の回帰テスト。
    """
    main = _record("AG1", "we should choose a")
    state = _fresh_state(main)
    state = replace(state, max_dialogue_turns=1)  # 根(main)だけで既に上限到達

    result = await _run_tree(
        state, attacks=[], counters=[], defeats=[], reverse_defeats=[]
    )

    assert result.tree_root_status == "defensible"
    assert result.tree_root_closed_by_budget is True


async def test_reinstatement_after_strict_defeat_is_justified() -> None:
    """B が A を defeat、C が B を strictly defeat、C への追撃なし ＝ justified.

    これは旧実装（C strictly defeats B の場合ただ o_defeat_a に戻るだけで、
    justified に到達する経路が「O が最初から1つも攻撃を出せない」場合しか
    無かった）で正しく扱えなかったケース。新実装では C 自身が新しいフレームとして
    push され、その C への攻撃が尽きた（None）ことで子フレームが won_by_p になり、
    それが親（root）に伝播して「この B は撃退された」として扱われ、その後 O が
    もう攻撃できなければ root も justified になる。
    """
    main = _record("AG1", "we should choose a")
    b_argument = ArgumentRecord(
        type="defeat",
        argument=json.dumps({"Argument": {"rules": [], "Conc": ["not a"], "Ass": []}}),
        support=[],
        agent="AG2",  # type: ignore[arg-type]
        attack="rebut",  # type: ignore[arg-type]
    )
    c_argument = ArgumentRecord(
        type="counter",
        argument=json.dumps({"Argument": {"rules": [], "Conc": ["not not a"], "Ass": []}}),
        support=[],
        agent="AG1",  # type: ignore[arg-type]
        attack="rebut",  # type: ignore[arg-type]
    )
    state = _fresh_state(main)

    result = await _run_tree(
        state,
        # 1本目の攻撃 B、2本目は無し（root では B しか出てこない）、
        # C への攻撃も無し（子フレームは即座に won_by_p）。
        attacks=[b_argument, None, None],
        counters=[c_argument],
        # defeats の消費順: B defeats A(=True), C defeats B(=True)
        defeats=[True, True],
        reverse_defeats=[False],  # B は C に反撃できない ＝ strictly defeat
    )

    assert result.tree_root_status == "justified"
    assert result.tree_root_closed_by_budget is False


async def test_mutual_defeat_is_defensible() -> None:
    """B が A を defeat、C が B を defeat するが B も C に反撃できる ＝ defensible.

    (mutual defeat: C は B を strictly defeat していない)
    """
    main = _record("AG1", "we should choose a")
    b_argument = ArgumentRecord(
        type="defeat",
        argument=json.dumps({"Argument": {"rules": [], "Conc": ["not a"], "Ass": []}}),
        support=[],
        agent="AG2",  # type: ignore[arg-type]
        attack="rebut",  # type: ignore[arg-type]
    )
    c_argument = ArgumentRecord(
        type="counter",
        argument=json.dumps({"Argument": {"rules": [], "Conc": ["not not a"], "Ass": []}}),
        support=[],
        agent="AG1",  # type: ignore[arg-type]
        attack="rebut",  # type: ignore[arg-type]
    )
    state = _fresh_state(main)
    state = replace(state, max_counter_attempts=1)

    result = await _run_tree(
        state,
        attacks=[b_argument],
        counters=[c_argument],
        defeats=[True, True],
        reverse_defeats=[True],  # B も C に反撃できる ＝ mutual defeat
    )

    assert result.tree_root_status == "defensible"
    assert result.tree_root_closed_by_budget is True


async def test_depth_four_recursion_reaches_justified() -> None:
    """A←B←C←D←E の深さ4まで探索し、Eへの攻撃が尽きて justified になることを確認する.

    C 自身が新しいフレームとして push され、そこへの攻撃 D が生成され、D を
    strictly defeat する E が生成され…と、旧実装では存在しなかった「C 以降への
    再帰的探索」が実際に機能することを検証する。
    """
    main = _record("AG1", "we should choose a")

    def rec(agent: str, tag: str) -> ArgumentRecord:
        return ArgumentRecord(
            type="defeat",
            argument=json.dumps({"Argument": {"rules": [], "Conc": [tag], "Ass": []}}),
            support=[],
            agent=agent,  # type: ignore[arg-type]
            attack="rebut",  # type: ignore[arg-type]
        )

    b_argument = rec("AG2", "B")
    c_argument = rec("AG1", "C")
    d_argument = rec("AG2", "D")
    e_argument = rec("AG1", "E")

    state = _fresh_state(main)

    result = await _run_tree(
        state,
        # depth0(root) の attack: B, その後 None(exhausted after repel)
        # depth1(=C, pushed as new frame) の attack: D
        # depth2(=E, pushed as new frame) の attack: None(exhausted)
        attacks=[b_argument, d_argument, None, None],
        # depth0 の counter: C ; depth1 の counter: E
        counters=[c_argument, e_argument],
        # defeats 消費順: B defeats A, C defeats B, D defeats C, E defeats D
        defeats=[True, True, True, True],
        # reverse 消費順: B defeats C? No ; D defeats E? No
        reverse_defeats=[False, False],
    )

    assert result.tree_root_status == "justified"


async def test_no_counter_available_is_overruled() -> None:
    """B が A を defeat、P が反論を1つも生成できない ＝ overruled."""
    main = _record("AG1", "we should choose a")
    b_argument = ArgumentRecord(
        type="defeat",
        argument=json.dumps({"Argument": {"rules": [], "Conc": ["not a"], "Ass": []}}),
        support=[],
        agent="AG2",  # type: ignore[arg-type]
        attack="rebut",  # type: ignore[arg-type]
    )
    state = _fresh_state(main)

    result = await _run_tree(
        state,
        attacks=[b_argument],
        counters=[None],
        defeats=[True],
        reverse_defeats=[],
    )

    assert result.tree_root_status == "overruled"
    assert result.tree_root_closed_by_budget is False
