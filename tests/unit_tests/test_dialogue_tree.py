"""dialogue tree（Prakken & Sartor, Definition 4.5/4.6）の再帰探索の単体テスト.

`opponent_move` / `validate_opponent_move` / `proponent_move` /
`validate_proponent_move` / `pop_and_propagate` / `resolve_tree_status` を、
LLM 呼び出し（`generate_attack` / `evaluate_attack` / `undercut_relation`）を
モックしながら実際に駆動し、木の解決（AND/OR 集約）が原論文の定義どおりに
動くことを検証する。
"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

import pytest

from agent.argumentation_model import AttackEvaluation
from agent.attack_judge import UndercutVerdict
from agent.edges import route_after_validate_proponent_move
from agent.schema.state import ArgumentRecord
from agent.workflow import State

pytestmark = pytest.mark.anyio


def _record(agent: str, conc: str) -> ArgumentRecord:
    payload = {"Argument": {"rules": [], "Conc": [conc], "Ass": []}}
    return ArgumentRecord(
        type="main",
        argument=json.dumps(payload),
        support=[],
        agent=agent,  # type: ignore[arg-type]
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

    async def fake_undercut_relation(_state, attack, _target, context="relation"):
        # strictly defeat の判定（SD(C, B) = U(C, B) ∧ ¬U(B, C)）で呼ばれる undercut の確認を、
        # reverse_defeats（B が C に反撃できるか＝相互 defeat か）から作って返す。
        #  - B → C（attack が反論側 B）: 相互 defeat のとき、B は C を undercut している（holds）。
        #  - C → B（attack が主張側 C）: 相互 defeat のとき、C は B を undercut していない（not holds）。
        mutual = next(reverse_iter)
        holds = (not mutual) if attack.agent == _state.current_proponent else mutual
        return UndercutVerdict(holds, None, "test")

    async def stage_aware_evaluate_attack(
        _state, attacker, target, _defender, **kwargs
    ):
        return AttackEvaluation(
            defeats=next(defeats_iter), attack=attacker.attack or "rebut", relations=[]
        )

    def _apply(update: dict[str, Any]) -> None:
        nonlocal state
        state = replace(state, **update)

    import agent.nodes as nodes_module

    original_generate_attack = nodes_module.generate_attack
    original_evaluate_attack = nodes_module.evaluate_attack
    original_undercut_relation = nodes_module.undercut_relation

    nodes_module.generate_attack = fake_generate_attack  # type: ignore[assignment]
    nodes_module.undercut_relation = fake_undercut_relation  # type: ignore[assignment]

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
                current = (
                    "proponent_move" if state.last_attack_defeated else "opponent_move"
                )
            elif current == "proponent_move":
                current = (
                    "validate_proponent_move"
                    if state.pending_counter_argument is not None
                    else "pop_and_propagate"
                )
            elif current == "validate_proponent_move":
                current = route_after_validate_proponent_move(state)
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
        nodes_module.undercut_relation = original_undercut_relation

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
        argument=json.dumps(
            {"Argument": {"rules": [], "Conc": ["not not a"], "Ass": []}}
        ),
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


async def test_mutual_defeat_without_other_attack_is_defensible() -> None:
    """B が A を defeat、C が B を defeat するが B も C に反撃できる ＝ 相互 defeat ＝ defensible.

    (Prakken & Sartor Def 3.4: B も C も defensible で、A は justified でも overruled でもない。
    フレームは閉じず、O は C への新しい攻撃を探すが、見つからなければ contested で閉じる。
    予算切れ扱いにはならない)
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
        argument=json.dumps(
            {"Argument": {"rules": [], "Conc": ["not not a"], "Ass": []}}
        ),
        support=[],
        agent="AG1",  # type: ignore[arg-type]
        attack="rebut",  # type: ignore[arg-type]
    )
    state = _fresh_state(main)

    result = await _run_tree(
        state,
        attacks=[b_argument],
        counters=[c_argument],
        defeats=[True, True],
        reverse_defeats=[True],  # B も C に反撃できる ＝ mutual defeat
    )

    assert result.tree_root_status == "defensible"
    assert result.tree_root_closed_by_budget is False
    assert "mutual_defeat" in [e["kind"] for e in result.attempt_log]


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


async def test_mutual_defeat_counter_is_not_retried() -> None:
    """B 1 つにつき P の返答は 1 つ。相互 defeat でも、2 つ目の反撃は作らず、defensible で閉じる.

    counters に、2 つ目の反撃を用意しておき、それが消費されないことを確かめる。
    """
    main = _record("AG1", "we should choose a")

    def rec(agent: str, tag: str, kind: str) -> ArgumentRecord:
        return ArgumentRecord(
            type=kind,  # type: ignore[arg-type]
            argument=json.dumps({"Argument": {"rules": [], "Conc": [tag], "Ass": []}}),
            support=[],
            agent=agent,  # type: ignore[arg-type]
            attack="rebut",  # type: ignore[arg-type]
        )

    b_argument = rec("AG2", "not a", "defeat")
    first_counter = rec("AG1", "first", "counter")
    second_counter = rec("AG1", "second", "counter")
    state = _fresh_state(main)

    result = await _run_tree(
        state,
        attacks=[b_argument],
        counters=[first_counter, second_counter],
        defeats=[True, True],  # B defeats A, 1 つ目の C defeats B
        reverse_defeats=[
            True
        ],  # B も C に反撃できる ＝ 相互 defeat ＝ strictly defeat にならない
    )

    assert result.tree_root_status == "defensible"
    assert result.tree_root_closed_by_budget is False
    counters_in_records = [r for r in result.argument_records if r.type == "counter"]
    assert len(counters_in_records) == 1  # 2 つ目の反撃は作られていない


def _rec(agent: str, tag: str, kind: str) -> ArgumentRecord:
    return ArgumentRecord(
        type=kind,  # type: ignore[arg-type]
        argument=json.dumps({"Argument": {"rules": [], "Conc": [tag], "Ass": []}}),
        support=[],
        agent=agent,  # type: ignore[arg-type]
        attack="rebut",  # type: ignore[arg-type]
    )


async def test_mutual_defeat_then_unanswered_attack_on_counter_is_overruled() -> None:
    """相互 defeat のあと、O が C を defeat する D を出し、P が返せなければ、C は負けて A は overruled."""
    result = await _run_tree(
        _fresh_state(_record("AG1", "we should choose a")),
        attacks=[_rec("AG2", "not a", "defeat"), _rec("AG2", "d", "defeat")],
        counters=[_rec("AG1", "c", "counter"), None],
        defeats=[True, True, True],  # B>A, C>B, D>C
        reverse_defeats=[True],
    )

    assert result.tree_root_status == "overruled"
    assert result.tree_root_closed_by_budget is False


async def test_mutual_defeat_branch_then_other_attack_repelled_stays_defensible() -> None:
    """相互 defeat の枝の後、別の B2 は strict に退けられても、A は justified にならず defensible."""
    result = await _run_tree(
        _fresh_state(_record("AG1", "we should choose a")),
        attacks=[_rec("AG2", "not a", "defeat"), None, _rec("AG2", "not a, again", "defeat")],
        counters=[_rec("AG1", "c", "counter"), _rec("AG1", "c2", "counter")],
        defeats=[True, True, True, True],  # B>A, C>B, B2>A, C2>B2
        reverse_defeats=[True, False],  # B⇄C は相互、B2 は C2 に反撃できない（strict）
    )

    assert result.tree_root_status == "defensible"
    assert result.tree_root_closed_by_budget is False


async def test_mutual_defeat_branch_then_other_attack_unanswered_is_overruled() -> None:
    """相互 defeat の枝の後、別の B2 に P が返せなければ、justified な B2 が A を倒すので overruled."""
    result = await _run_tree(
        _fresh_state(_record("AG1", "we should choose a")),
        attacks=[_rec("AG2", "not a", "defeat"), None, _rec("AG2", "not a, again", "defeat")],
        counters=[_rec("AG1", "c", "counter"), None],
        defeats=[True, True, True],  # B>A, C>B, B2>A
        reverse_defeats=[True],
    )

    assert result.tree_root_status == "overruled"


def _counter_rec(agent: str, tag: str, kind: str) -> ArgumentRecord:
    return ArgumentRecord(
        type=kind,  # type: ignore[arg-type]
        argument=json.dumps({"Argument": {"rules": [], "Conc": [tag], "Ass": []}}),
        support=[],
        agent=agent,  # type: ignore[arg-type]
        attack="rebut",  # type: ignore[arg-type]
    )


async def test_counter_that_does_not_defeat_is_retried_and_can_then_succeed() -> None:
    """反撃 C が B を defeat できなくても、P は同じ B への別の反撃をやり直せる.

    文献（Def 4.8）は、P が勝つ木が存在することを証明の条件とし、P は返答を探してよい。
    弾かれた C も、履歴に残り、ターン数に数える。
    """
    main = _record("AG1", "we should choose a")
    state = _fresh_state(main)

    result = await _run_tree(
        state,
        attacks=[_counter_rec("AG2", "not a", "defeat"), None],
        counters=[_counter_rec("AG1", "first", "counter"), _counter_rec("AG1", "second", "counter")],
        defeats=[True, False, True],  # B>A、1 つ目の C は B を defeat しない、2 つ目の C は defeat する
        reverse_defeats=[False],  # 2 つ目の C は strictly defeat
    )

    assert result.tree_root_status == "justified"
    # 弾かれた C も、やり直した C も、履歴（ターン数の対象）に残る。
    assert [r.type for r in result.argument_records].count("counter") == 2


async def test_proponent_with_no_new_counter_after_a_rejection_loses_the_branch() -> None:
    """弾かれたあと、P が新しい反撃を作れなければ（no_counter）、その枝は P の負け."""
    main = _record("AG1", "we should choose a")
    state = _fresh_state(main)

    result = await _run_tree(
        state,
        attacks=[_counter_rec("AG2", "not a", "defeat")],
        counters=[_counter_rec("AG1", "first", "counter"), None],
        defeats=[True, False],
        reverse_defeats=[],
    )

    assert result.tree_root_status == "overruled"
    assert [r.type for r in result.argument_records].count("counter") == 1


async def test_rejected_counters_count_toward_the_turn_budget() -> None:
    """やり直した反撃は、ターン数に数えられ、予算が尽きると、その枠は undetermined（defensible）で閉じる."""
    main = _record("AG1", "we should choose a")
    state = replace(_fresh_state(main), max_dialogue_turns=6)  # AG1 の予算は 3 発話（main を含む）

    result = await _run_tree(
        state,
        attacks=[_counter_rec("AG2", "not a", "defeat"), None],
        counters=[_counter_rec("AG1", f"c{i}", "counter") for i in range(10)],
        defeats=[True] + [False] * 10,
        reverse_defeats=[],
    )

    assert result.tree_root_status == "defensible"
    assert result.tree_root_closed_by_budget is True
    # main 1 + B 1 + 弾かれた C が、予算 3 に達するまで。
    assert len(result.argument_records) == 3


def test_route_after_validate_proponent_move() -> None:
    """defeat した C は opponent_move へ、弾かれた C は proponent_move へ戻る（やり直し）."""
    from agent.edges import route_after_validate_proponent_move

    rejected = State(question="Q?", agent1_stance="s1", agent2_stance="s2")
    rejected.last_counter_strictly_defeated = False
    rejected.last_counter_rejected = True
    assert route_after_validate_proponent_move(rejected) == "proponent_move"

    succeeded = State(question="Q?", agent1_stance="s1", agent2_stance="s2")
    succeeded.last_counter_strictly_defeated = True
    succeeded.last_counter_rejected = False
    assert route_after_validate_proponent_move(succeeded) == "opponent_move"

    neither = State(question="Q?", agent1_stance="s1", agent2_stance="s2")
    assert route_after_validate_proponent_move(neither) == "pop_and_propagate"
