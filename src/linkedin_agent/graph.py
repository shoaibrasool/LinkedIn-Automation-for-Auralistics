from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from linkedin_agent.banned_phrases import MAX_AUTHENTICITY_RETRIES
from linkedin_agent.nodes.authenticity_node import authenticity_node
from linkedin_agent.nodes.draft_node import draft_node
from linkedin_agent.nodes.search_node import search_node


class GraphState(TypedDict):
    topic: str
    search_results: str
    draft: str | None
    authenticity_result: dict | None
    retry_count: int
    flagged_for_manual: bool
    authenticity_feedback: str


def route_after_authenticity(state: GraphState) -> Literal["draft", "end"]:
    result = state.get("authenticity_result") or {}
    if result.get("passed", False):
        return "end"
    if state.get("flagged_for_manual", False):
        return "end"
    return "draft"


def build_graph() -> StateGraph:
    builder = StateGraph(GraphState)
    builder.add_node("search", search_node)
    builder.add_node("draft", draft_node)
    builder.add_node("authenticity", authenticity_node)

    builder.add_edge(START, "search")
    builder.add_edge("search", "draft")
    builder.add_edge("draft", "authenticity")

    builder.add_conditional_edges(
        "authenticity",
        route_after_authenticity,
        {
            "draft": "draft",
            "end": END,
        },
    )

    return builder.compile()
