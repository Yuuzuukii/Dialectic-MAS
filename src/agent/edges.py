"""LangGraph の条件分岐エッジ。state を見て次ノード名を返すルーティング関数群."""

from __future__ import annotations

import os
from typing import Any


def _int_env(name: str, default: int) -> int:
    """環境変数を int として読む。未設定または空文字なら default を返す."""
    value = os.getenv(name)
    return int(value) if value else default


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
    """相手の主張 A に対する自己反論ステップ後の遷移先を決める."""
    if state.error:
        return "finish_with_error"
    if state.current_thread_status == "justified":
        return "generate_final_answer"
    if state.b_argument is None:
        return "finish"
    return "validate_b_defeats_a"


def route_after_validate_b_defeats_a(state: Any) -> str:
    """B が A を破る関係の検証後の遷移先を決める."""
    if state.error:
        return "finish_with_error"
    if state.current_thread_status == "justified":
        return "generate_final_answer"
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
    if state.current_thread_status in {"justified", "defensible"}:
        return "route_after_thread"
    return "finish_with_error"


def route_after_thread(state: Any) -> str:
    """1スレッド分の議論終了後、次の遷移先を決める."""
    if state.error:
        return "finish_with_error"
    if state.current_thread_status == "justified":
        return "generate_final_answer"
    # justified 以外（overruled / defensible）→ 試行回数の上限に達していなければ
    # 同じ proponent に別の main argument を試させる。
    if state.main_attempt_count < state.max_main_argument_attempts:
        return "can_generate_main"
    # 上限に達した場合は can_generate_main を呼ばず、available=NO のときと同じ遷移を行う。
    if state.current_proponent == "AG1":
        return "advance_to_ag2"
    return "extract_warrants"


def route_after_synthesis_step(state: Any) -> str:
    """統合ステップ後の遷移先を決める."""
    if state.error:
        return "finish_with_error"
    return "next"


