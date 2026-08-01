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
    return "o_defeat_a"


def route_after_o_defeat_a(state: Any) -> str:
    """相手の主張 A に対する自己反論ステップ後の遷移先を決める.

    `o_defeat_a` はリトライ回数の上限に達した場合、新しい攻撃を生成せずに
    `current_thread_status="defensible"` で即座に返ってくる（予算切れによる打ち切り
    は、真の手詰まりである justified とは区別する）。justified（Opponent が
    そもそも攻撃を生成できなかった＝手詰まり）も含め、いずれの終了ステータスでも
    ここでは対話を打ち切らず、他の overruled と同様 route_after_thread に合流させて
    次の main argument の生成を試みさせる（最終回答生成は主張が尽きたときのみ）。
    """
    if state.error:
        return "finish_with_error"
    if state.current_thread_status in {"justified", "defensible"}:
        return "route_after_thread"
    if state.b_argument is None:
        return "finish"
    return "validate_b_defeats_a"


def route_after_validate_b_defeats_a(state: Any) -> str:
    """B が A を破る関係の検証後の遷移先を決める."""
    if state.error:
        return "finish_with_error"
    if state.thread_needs_retry:
        return "o_defeat_a"
    if state.b_defeats_a is True:
        return "p_counter_b"
    return "finish_with_error"


def route_after_p_counter_b(state: Any) -> str:
    """B への反論 C の生成ステップ後の遷移先を決める."""
    if state.error:
        return "finish_with_error"
    if state.current_thread_status == "overruled":
        return "route_after_thread"
    if state.c_argument is None:
        return "route_after_thread"
    return "validate_c_defeats_b"


def route_after_validate_c_defeats_b(state: Any) -> str:
    """C が B を破る関係の検証後の遷移先を決める."""
    if state.error:
        return "finish_with_error"
    if state.current_thread_status == "overruled":
        return "route_after_thread"
    if state.c_defeats_b is True:
        return "validate_b_defeats_c"
    return "finish_with_error"


def route_after_validate_b_defeats_c(state: Any) -> str:
    """B が C を破り返す関係の検証後の遷移先を決める."""
    if state.error:
        return "finish_with_error"
    if state.thread_needs_retry:
        return "o_defeat_a"
    if state.current_thread_status in {"justified", "defensible"}:
        return "route_after_thread"
    return "finish_with_error"


def route_after_thread(state: Any) -> str:
    """1スレッド分の議論終了後、次の遷移先を決める.

    justified / overruled / defensible のいずれで終わっても、この main argument
    の決着として扱う（同じ main argument へのリトライはしない。Opponent の
    攻撃リトライ回数の上限判定は o_defeat_a の入り口で既に行われている）。
    justified になっただけでは対話を打ち切らない（この状態は
    argument_records/dialogue_history に記録済みで、後から追跡できる）。
    次の proponent（AG2）に手番を渡すか、両者が出し切っていれば統合フェーズへ進む。
    最終回答は、両者が新しい主張を出せなくなった時点（route_after_extract_warrants）
    かラウンド上限到達時（finalize_fallback）に初めて生成される。
    """
    if state.error:
        return "finish_with_error"
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


