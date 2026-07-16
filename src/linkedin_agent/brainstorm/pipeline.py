import logging
from datetime import datetime, timezone
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from tavily import TavilyClient

from linkedin_agent.brainstorm.angle_scorer import score_angles
from linkedin_agent.brainstorm.brainstorm_node import brainstorm_node
from linkedin_agent.brainstorm.dedup import dedup_angles, upsert_angle_vectors
from linkedin_agent.config import get_tavily_api_key

logger = logging.getLogger(__name__)

MAX_ANGLES_TO_KEEP = 4
MIN_ANGLES_TO_KEEP = 2


class BrainstormState(TypedDict):
    scored_idea: dict
    research_context: str
    angles: list[dict]
    scored_angles: list[dict]
    deduped_angles: list[dict]
    top_angles: list[dict]


def research_angle_node(state: BrainstormState) -> dict:
    """Do a fresh Tavily search for the idea topic before brainstorming angles."""
    idea = state["scored_idea"]
    idea_text = idea.get("generated_idea", "") or ""
    hook = idea.get("hook", "")

    api_key = get_tavily_api_key()
    client = TavilyClient(api_key=api_key)

    current_date = datetime.now(timezone.utc).strftime("%B %d, %Y")
    query = f"{hook} {idea_text} {current_date}"

    try:
        response = client.search(
            query=query,
            search_depth="advanced",
            max_results=6,
            include_answer=True,
        )
        snippets = []
        if answer := response.get("answer"):
            snippets.append(f"[Tavily Summary]: {answer}")
        for result in response.get("results", []):
            content = result.get("content", "")
            url = result.get("url", "")
            if content:
                snippets.append(f"[{url}]: {content[:500]}")
        return {"research_context": "\n\n".join(snippets) if snippets else "No fresh web results found."}
    except Exception as e:
        logger.warning("Research angle search failed: %s", e)
        return {"research_context": "No fresh web results found. Rely on the idea text only."}


def generate_angles_node(state: BrainstormState) -> dict:
    result = brainstorm_node(
        scored_idea=state["scored_idea"],
        research_context=state.get("research_context", ""),
    )
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

    builder.add_node("research_angle", research_angle_node)
    builder.add_node("generate_angles", generate_angles_node)
    builder.add_node("score_angles", score_angles_node)
    builder.add_node("dedup_angles", dedup_angles_node)
    builder.add_node("select_top", select_top_angles_node)

    builder.add_edge(START, "research_angle")
    builder.add_edge("research_angle", "generate_angles")
    builder.add_edge("generate_angles", "score_angles")
    builder.add_edge("score_angles", "dedup_angles")
    builder.add_edge("dedup_angles", "select_top")
    builder.add_edge("select_top", END)

    return builder.compile()


def brainstorm(scored_idea: dict) -> list[dict[str, Any]]:
    graph = build_brainstorm_graph()
    initial_state: BrainstormState = {
        "scored_idea": scored_idea,
        "research_context": "",
        "angles": [],
        "scored_angles": [],
        "deduped_angles": [],
        "top_angles": [],
    }
    result = graph.invoke(initial_state)
    return result.get("top_angles", [])
