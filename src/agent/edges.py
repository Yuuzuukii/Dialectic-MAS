from __future__ import annotations

from typing import Any


def route_after_can_generate_main(state: Any) -> str:
    if state.error:
        return "finish_with_error"
    if state.main_argument_available is False:
        return "finish"
    if state.finalize_mode:
        return "finalize_fallback"
    return "o_defeat_a"


def route_after_o_defeat_a(state: Any) -> str:
    if state.error:
        return "finish_with_error"
    if state.current_thread_status == "justified":
        return "generate_final_answer"
    if state.b_argument is None:
        return "finish"
    return "validate_b_defeats_a"


def route_after_validate_b_defeats_a(state: Any) -> str:
    if state.error:
        return "finish_with_error"
    if state.current_thread_status == "justified":
        return "generate_final_answer"
    if state.b_defeats_a is True:
        return "p_counter_b"
    return "finish_with_error"


def route_after_p_counter_b(state: Any) -> str:
    if state.error:
        return "finish_with_error"
    if state.current_thread_status == "overruled":
        return "route_after_thread"
    if state.c_argument is None:
        return "route_after_thread"
    return "validate_c_defeats_b"


def route_after_validate_c_defeats_b(state: Any) -> str:
    if state.error:
        return "finish_with_error"
    if state.current_thread_status == "overruled":
        return "route_after_thread"
    if state.c_defeats_b is True:
        return "validate_b_defeats_c"
    return "finish_with_error"


def route_after_validate_b_defeats_c(state: Any) -> str:
    if state.error:
        return "finish_with_error"
    if state.current_thread_status in {"justified", "defensible"}:
        return "route_after_thread"
    return "finish_with_error"


def route_after_thread(state: Any) -> str:
    if state.error:
        return "finish_with_error"
    if state.current_thread_status == "justified":
        return "generate_final_answer"
    if state.ag1_thread_status is not None and state.ag2_thread_status is not None:
        return "extract_warrants"
    return "can_generate_main"


def route_after_synthesis_step(state: Any) -> str:
    if state.error:
        return "finish_with_error"
    return "next"


def route_after_add_integrated_rule(state: Any) -> str:
    if state.error:
        return "finish_with_error"
    # finalize_mode のときは can_generate_main → finalize_fallback で確実に終端するため、
    # ここでは常に can_generate_main へ戻す。上限超過は安全弁として finish。
    if state.debate_round > state.max_turns:
        return "finish"
    return "can_generate_main"
