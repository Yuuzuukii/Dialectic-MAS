import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field, field_validator

from src.agent.graphs.dialectic_workflow import State, graph

app = FastAPI()

INTERNAL_STATE_FIELDS = {
    "last_generated_argument",
    "current_argument",
    "active_agent",
    "debate_stage",
    "turn_count",
    "last_can_defeat",
    "last_generated_argument_appended",
    "ag1_main_argument",
    "ag2_main_argument",
    "ag1_pending",
    "ag2_pending",
    "history",
    "warrant_result",
    "generalization_result",
    "integration_result",
    "b_defeats_a",
    "c_defeats_b",
    "b_defeats_c",
    "c_strictly_defeats_b",
}

AG1_STANCE = """
        Your stance:
        a is curry rice.
        c is curry noodles.
        a has curry flavor.
        c has curry flavor.
        b is not acceptable to you.
        If a menu has curry flavor, we should eat it.
        If something is not acceptable to you, we should not eat it.
        """

AG2_STANCE = """
        Your stance:
        b is Chinese noodles.
        c is curry noodles.
        b is a noodle dish.
        c is a noodle dish.
        a is not acceptable to you.
        If a menu is a noodle dish, we should eat it.
        If something is not acceptable to you, we should not eat it.
        """

QUESTION = "What should we eat?"


def public_result(result: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in result.items() if key not in INTERNAL_STATE_FIELDS}


class DialogueRequest(BaseModel):
    question: str = QUESTION
    agent1_stance: str = AG1_STANCE
    agent2_stance: str = AG2_STANCE
    max_turns: int = Field(default=5, ge=1)
    additional_context: dict[str, Any] = Field(default_factory=dict)
    output_path: str = "result/dialogue_result.json"

    @field_validator("agent1_stance", mode="before")
    @classmethod
    def default_agent1_stance_when_blank(cls, value: Any) -> str:
        if value is None or (isinstance(value, str) and not value.strip()):
            return AG1_STANCE
        return value

    @field_validator("agent2_stance", mode="before")
    @classmethod
    def default_agent2_stance_when_blank(cls, value: Any) -> str:
        if value is None or (isinstance(value, str) and not value.strip()):
            return AG2_STANCE
        return value


@app.post("/invoke")
async def invoke_dialogue(request: DialogueRequest):
    graph_input = State(**request.model_dump(exclude={"output_path"}))
    result = await graph.ainvoke(graph_input)
    encoded_result = jsonable_encoder(public_result(result))

    output_path = Path(request.output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(encoded_result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return {
        "saved_path": str(output_path),
        "result": encoded_result,
    }


@app.get("/")
def health_check():
    return {"status": "ok"}
