from __future__ import annotations

from typing import Any, Literal


Route = Literal[
    "generate_argument",
    "generate_defeat",
    "extract_warrants",
    "early_finish",
    "max_turn_error",
]


def route_after_argument(state: Any) -> Route:
    return "generate_defeat"


def route_after_defeat(state: Any) -> Route:
    if state.error:
        return "max_turn_error"

    if state.last_can_defeat is True:
        if state.last_defeat_target_was_main:
            if state.debate_stage == "ag1_main_thread" and state.ag2_main_argument is None:
                return "generate_argument"
            return "extract_warrants"

        if state.turn_count >= state.max_turns:
            return "max_turn_error"

        return "generate_defeat"

    if state.last_can_defeat is False:
        if (
            state.debate_stage == "ag1_main_thread"
            and state.current_argument is not None
            and state.ag1_main_argument is not None
            and state.current_argument.id == state.ag1_main_argument.id
        ):
            return "early_finish"

        if state.debate_stage == "ag1_main_thread" and state.ag2_main_argument is None:
            return "generate_argument"

        return "extract_warrants"

    return "max_turn_error"
