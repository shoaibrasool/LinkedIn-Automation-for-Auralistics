import logging
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from linkedin_agent.brainstorm.angle_scorer import score_angles
from linkedin_agent.brainstorm.brainstorm_node import brainstorm_node
from linkedin_agent.brainstorm.dedup import dedup_angles, upsert_angle_vectors

logger = logging.getLogger(__name__)

MAX_ANGLES_TO_KEEP = 4
MIN_ANGLES_TO_KEEP = 2


class BrainstormState(TypedDict):
    scored_idea: dict
    angles: list[dict]
    scored_angles: list[dict]
    deduped_angles: list[dict]
    top_angles: list[dict]


def generate_angles_node(state: BrainstormState) -> dict:
    result = brainstorm_node(state["scored_idea"])
    return {"angles": result.get("angles", [])}


def score_angles_node(state: BrainstormState) -> dict:
    angles = state.get("angles", [])
    if not angles:
        return {"scored_angles": []}
    scored = score_angles(angles)
    return {"scored_angles": scored}


def dedup_angles_node(state: BrainstormState) -> dict:
    angles = state.get("scored_angles", [])
    if not angles:
        return {"deduped_angles": []}
    deduped = dedup_angles(angles)
    return {"deduped_angles": deduped}


def select_top_angles_node(state: BrainstormState) -> dict:
    angles = state.get("deduped_angles", [])
    if not angles:
        angles = state.get("scored_angles", [])
    if not angles:
        return {"top_angles": []}

    sorted_angles = sorted(
        angles,
        key=lambda a: a.get("total_score", 0),
        reverse=True,
    )

    keep_count = max(MIN_ANGLES_TO_KEEP, min(MAX_ANGLES_TO_KEEP, len(sorted_angles)))
    top = sorted_angles[:keep_count]

    idea_id = state.get("scored_idea", {}).get("id")
    upsert_angle_vectors(top, idea_id=str(idea_id) if idea_id else None)

    logger.info(
        "Selected top %d/%d angles for idea '%s'",
        len(top),
        len(sorted_angles),
        (state.get("scored_idea", {}).get("generated_idea") or "")[:60],
    )

    return {"top_angles": top}


def build_brainstorm_graph() -> StateGraph:
    builder = StateGraph(BrainstormState)

    builder.add_node("generate_angles", generate_angles_node)
    builder.add_node("score_angles", score_angles_node)
    builder.add_node("dedup_angles", dedup_angles_node)
    builder.add_node("select_top", select_top_angles_node)

    builder.add_edge(START, "generate_angles")
    builder.add_edge("generate_angles", "score_angles")
    builder.add_edge("score_angles", "dedup_angles")
    builder.add_edge("dedup_angles", "select_top")
    builder.add_edge("select_top", END)

    return builder.compile()


def brainstorm(scored_idea: dict) -> list[dict[str, Any]]:
    graph = build_brainstorm_graph()
    initial_state: BrainstormState = {
        "scored_idea": scored_idea,
        "angles": [],
        "scored_angles": [],
        "deduped_angles": [],
        "top_angles": [],
    }
    result = graph.invoke(initial_state)
    return result.get("top_angles", [])
