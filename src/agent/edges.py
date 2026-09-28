"""LangGraph の条件分岐エッジ。state を見て次ノード名を返すルーティング関数群."""

from __future__ import annotations

import os
from typing import Any


def _int_env(name: str, default: int) -> int:
    """環境変数を int として読む。未設定または空文字なら default を返す."""
    value = os.getenv(name)
    return int(value) if value else default


def _optional_int_env(name: str) -> int | None:
    """環境変数を int として読む。未設定または空文字なら None を返す.

    `max_dialogue_turns`（全手法共通の絶対ターン数上限）の既定値に使う。None のときは
    無効（既存の round/attempts ベースの上限だけで従来通り動く）ことを示す。

    schema では、片方の main argument を巡る攻防が長引くともう片方が今ラウンド
    一度も発言できなくなる問題があるため、この値を AG1/AG2 で折半して使う
    （`nodes.py` の `_per_proponent_dialogue_turn_budget` 参照）。MAD/Free Debate は
    厳密な交互発言で自然に均等になるため、折半せず共有の絶対値のまま使う。
    """
    value = os.getenv(name)
    return int(value) if value else None


def route_round_entry(state: Any) -> str:
    """各ラウンドの開始点（プロトコル周回数の判定）.

    ラウンド上限に達したかどうかを、主張可否判定よりも前に・無条件で判定する
    関門。START 直後と、統合フェーズ（add_integrated_rule）の直後の両方から
    呼ばれる。ここで上限到達と判定されれば、主張可否判定を一切経由せず
    finalize_fallback（→generate_final_answer）に直行するため、
    「上限到達後に主張可否判定の結果でfinal_answer生成が握り潰される」という
    旧実装のバグはこの構造では発生し得ない。
    """
    if state.error:
        return "finish_with_error"
    if state.debate_round > state.max_turns:
        return "finalize_fallback"
    return "can_generate_main"


def route_after_can_generate_main(state: Any) -> str:
    """主張生成の可否判定後の遷移先を決める."""
    if state.error:
        return "finish_with_error"
    if state.main_argument_available is False:
        if state.current_proponent == "AG1":
            return "advance_to_ag2"
        return "extract_warrants"
    return "init_dialogue_tree"


# ----------------------------------------------------------------------------
# dialogue tree（Definition 4.5/4.6）の探索ルーティング
#
# opponent_move ⇄ validate_opponent_move: 現フレームの argument への攻撃 (B) を
#   Opponent が生成し、defeat 判定を行う。defeat できなければ同じフレームで
#   opponent_move に戻り別の B' を試す。
# proponent_move ⇄ validate_proponent_move: B に対する反論 (C) を Proponent が
#   生成し、strictly defeat かどうかを判定する。strictly defeat しなければ同じ
#   フレームで proponent_move に戻り別の C' を試す。strictly defeat すれば C を
#   argument_id とする子フレームを push し、opponent_move へ戻って1段深く探索する。
# pop_and_propagate: フレームが閉じた（won_by_p/lost_by_p/undetermined）ときに
#   呼ばれ、親フレームへ結果を伝播する。根が閉じれば resolve_tree_status へ。
# ----------------------------------------------------------------------------


def route_after_init_dialogue_tree(state: Any) -> str:
    """Dialogue tree 初期化後の遷移先を決める."""
    if state.error:
        return "finish_with_error"
    return "opponent_move"


def route_after_opponent_move(state: Any) -> str:
    """Opponent の攻撃生成後の遷移先を決める.

    フレームが閉じた場合（新しい攻撃を生成できなかった / 予算切れ）は
    `pending_attacker_argument` が None のまま返るので、それをフレーム終了の
    シグナルとして使う。
    """
    if state.error:
        return "finish_with_error"
    if state.pending_attacker_argument is None:
        return "pop_and_propagate"
    return "validate_opponent_move"


def route_after_validate_opponent_move(state: Any) -> str:
    """B が対象を defeat するかの検証後の遷移先を決める."""
    if state.error:
        return "finish_with_error"
    if state.last_attack_defeated is True:
        return "proponent_move"
    return "opponent_move"


def route_after_proponent_move(state: Any) -> str:
    """Proponent の反論生成後の遷移先を決める（フレームが閉じたかどうかで分岐）."""
    if state.error:
        return "finish_with_error"
    if state.pending_counter_argument is None:
        return "pop_and_propagate"
    return "validate_proponent_move"


def route_after_validate_proponent_move(state: Any) -> str:
    """C が B を strictly defeat するかの検証後の遷移先を決める."""
    if state.error:
        return "finish_with_error"
    if state.last_counter_strictly_defeated is True:
        return "opponent_move"
    return "proponent_move"


def route_after_pop_and_propagate(state: Any) -> str:
    """フレームの pop・伝播後の遷移先を決める（根まで伝播しきったかどうかで分岐）."""
    if state.error:
        return "finish_with_error"
    if state.last_propagation_action == "resolved":
        return "resolve_tree_status"
    if state.last_propagation_action == "retry_attack":
        return "opponent_move"
    return "pop_and_propagate"


def route_after_resolve_tree_status(state: Any) -> str:
    """1つの main argument の dialogue tree が確定した後の遷移先を決める.

    justified なら最終回答へ（Prakken & Sartor に忠実: justified な論証が
    そのまま対話の結論になる。両者の意見の取り込みは統合フェーズが別途担う）。
    overruled / defensible なら、Proponent の main argument はこの1本で確定とし、
    次の proponent（AG2）に手番を渡すか、両者が出し切っていれば統合フェーズへ進む。
    """
    if state.error:
        return "finish_with_error"
    if state.tree_root_status == "justified":
        return "generate_final_answer"
    if state.current_proponent == "AG1":
        return "advance_to_ag2"
    return "extract_warrants"


def route_after_synthesis_step(state: Any) -> str:
    """統合ステップ後の遷移先を決める."""
    if state.error:
        return "finish_with_error"
    return "next"


def route_after_extract_warrants(state: Any) -> str:
    """ワラント抽出後の遷移先を決める.

    AG1・AG2 のどちらかが今ラウンドで新しい main argument を生成できなかった場合、
    次ラウンド用のルールを両者から統合する材料が揃わない（統合しても使われない：
    片方が主張を尽くした時点で次ラウンドは行われない）。この場合は
    integrate（汎化+統合）をスキップし、finalize_fallback で決着させる。
    """
    if state.error:
        return "finish_with_error"
    if state.ag1_main_argument is None or state.ag2_main_argument is None:
        return "finalize_fallback"
    return "next"
