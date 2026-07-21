import logging
import threading
from datetime import datetime, timezone
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from tavily import TavilyClient

from linkedin_agent.brainstorm.angle_scorer import score_angles
from linkedin_agent.brainstorm.brainstorm_node import brainstorm_node
from linkedin_agent.brainstorm.dedup import dedup_angles, upsert_angle_vectors
from linkedin_agent.config import get_tavily_api_key

_thread_local = threading.local()


def _set_progress_callback(cb):
    _thread_local.progress_callback = cb

def _get_progress_callback():
    return getattr(_thread_local, 'progress_callback', None)

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
    cb = _get_progress_callback()
    if cb:
        cb("brainstorm_research", "Researching angle context via Tavily...", 10)
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
            title = result.get("title", "")
            if content:
                snippets.append(f"[{title}]({url}): {content[:500]}")
        context = "\n\n".join(snippets)
    except Exception as e:
        logger.warning("Research angle search failed: %s", e)
        context = "No fresh web results found."

    cb = _get_progress_callback()
    if cb:
        cb("brainstorm_research_done", "Research complete", 20)
    return {"research_context": context}


def generate_angles_node(state: BrainstormState) -> dict:
    cb = _get_progress_callback()
    if cb:
        cb("brainstorm_generating", "Generating 15-20 angles via Gemini...", 30)
    result = brainstorm_node(
        scored_idea=state["scored_idea"],
        research_context=state.get("research_context", ""),
    )
    if cb:
        angles = result.get("angles", [])
        cb("brainstorm_generating_done", f"{len(angles)} angles generated", 50)
    return {"angles": result.get("angles", [])}


def score_angles_node(state: BrainstormState) -> dict:
    cb = _get_progress_callback()
    if cb:
        cb("brainstorm_scoring", "Scoring angles via Groq LLaMA...", 60)
    angles = state.get("angles", [])
    if not angles:
        return {"scored_angles": []}
    scored = score_angles(angles)
    if cb:
        cb("brainstorm_scoring_done", f"{len(scored)} angles scored", 75)
    return {"scored_angles": scored}


def dedup_angles_node(state: BrainstormState) -> dict:
    cb = _get_progress_callback()
    if cb:
        cb("brainstorm_dedup", "Deduplicating against past angles...", 80)
    angles = state.get("scored_angles", [])
    if not angles:
        return {"deduped_angles": []}
    deduped = dedup_angles(angles)
    if cb:
        cb("brainstorm_dedup_done", f"{len(deduped)} unique angles after dedup", 85)
    return {"deduped_angles": deduped}


def select_top_angles_node(state: BrainstormState) -> dict:
    cb = _get_progress_callback()
    if cb:
        cb("brainstorm_select", "Selecting top angles...", 90)
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

    cb = _get_progress_callback()
    if cb:
        cb("brainstorm_done", f"Done — {len(top)} top angles ready", 100)

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


def brainstorm(scored_idea: dict, progress_callback=None) -> list[dict[str, Any]]:
    _set_progress_callback(progress_callback)
    graph = build_brainstorm_graph()
    initial_state: BrainstormState = {
        "scored_idea": scored_idea,
        "research_context": "",
        "angles": [],
        "scored_angles": [],
        "deduped_angles": [],
        "top_angles": [],
    }
    try:
        result = graph.invoke(initial_state)
        return result.get("top_angles", [])
    finally:
        _set_progress_callback(None)
