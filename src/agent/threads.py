"""Thread bookkeeping helpers used by graph nodes."""

from __future__ import annotations

from typing import Any

try:
    from .schema.state import ArgumentRecord
except ImportError:  # pragma: no cover - supports LangGraph file-path loading.
    from schema.state import ArgumentRecord


def dialogue_history(history: list[ArgumentRecord]) -> list[dict[str, Any]]:
    return [argument.to_dialogue_dict() for argument in history]


def thread_finding(state: Any, status: str) -> str | None:
    if state.current_argument is None or state.b_argument is None:
        return None
    main_conclusion = "; ".join(state.current_argument.conclusions) or "the previous main argument"
    defeating_conclusion = "; ".join(state.b_argument.conclusions) or "the defeating argument"
    if status == "overruled":
        return (
            f"{state.current_proponent}'s previous main argument ({main_conclusion}) was overruled by "
            f"{state.current_opponent}'s {state.b_argument.attack} ({defeating_conclusion}). "
            "Do not repeat the same main argument unless this defeating reason is resolved."
        )
    if status == "defensible":
        return (
            f"{state.current_proponent}'s previous main argument ({main_conclusion}) remained defensible, "
            f"with an unresolved conflict against {state.current_opponent}'s {state.b_argument.attack} "
            f"({defeating_conclusion}). "
            "Do not repeat the same main argument as if the conflict were resolved."
        )
    return None


def _annotate_main_status(
    history: list[ArgumentRecord], main_id: str | None, status: str
) -> list[ArgumentRecord]:
    """スレッド完了時、対象 main レコードの status を後追いで埋める（不変＝コピーで差し替え）。"""
    if main_id is None:
        return history
    return [
        record.model_copy(update={"status": status}) if record.id == main_id else record
        for record in history
    ]


def complete_thread(
    state: Any,
    status: str,
    extra_history: list[ArgumentRecord] | None = None,
) -> dict[str, Any]:
    key = "ag1" if state.current_proponent == "AG1" else "ag2"
    main_id = state.current_argument.id if state.current_argument else None
    history = _annotate_main_status(
        [*state.history, *(extra_history or [])], main_id, status
    )
    update: dict[str, Any] = {
        "current_thread_status": status,
        "history": history,
        "dialogue_history": dialogue_history(history),
        f"{key}_thread_status": status,
    }

    finding = thread_finding(state, status)
    if finding is not None and finding not in state.learned_findings:
        update["learned_findings"] = [*state.learned_findings, finding]

    if status == "justified":
        update["justified_argument"] = state.current_argument.argument if state.current_argument else None
        update["justification_status"] = f"{key}_main_justified"
        update["consensus_reached"] = True
    elif status == "overruled":
        update["justification_status"] = f"{key}_main_overruled"

    if status in {"defensible", "overruled"}:
        update["current_proponent"] = state.current_proponent
        update["current_opponent"] = state.current_opponent
        if key == "ag1" and state.ag2_thread_status is None:
            update.update(
                {
                    "current_proponent": "AG2",
                    "current_opponent": "AG1",
                    "active_agent": "AG2",
                    "current_argument": None,
                    "b_argument": None,
                    "c_argument": None,
                    "d_argument": None,
                    "b_argument_id": None,
                    "c_argument_id": None,
                    "d_argument_id": None,
                    "b_defeats_a": None,
                    "c_defeats_b": None,
                    "b_defeats_c": None,
                    "c_strictly_defeats_b": None,
                    "debate_stage": "ag2_main_thread",
                }
            )
    return update
