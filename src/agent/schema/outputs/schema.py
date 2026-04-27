from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


AgentName = Literal["AG1", "AG2"]
DebateStage = Literal["ag1_main_thread", "ag2_main_thread"]
ArgumentType = Literal["main", "defeat"]


class ArgumentRecord(BaseModel):
    type: ArgumentType
    argument: str
    support: list[str] = Field(default_factory=list)
    agent: AgentName

    def to_dialogue_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "argument": self.argument,
            "support": self.support,
            "agent": self.agent,
        }
