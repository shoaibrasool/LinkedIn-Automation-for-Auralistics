from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from linkedin_agent.nodes.draft_node import draft_node
from linkedin_agent.nodes.search_node import search_node


class GraphState(TypedDict):
    topic: str
    search_results: str
    draft: str | None


def build_graph() -> StateGraph:
    builder = StateGraph(GraphState)
    builder.add_node("search", search_node)
    builder.add_node("draft", draft_node)
    builder.add_edge(START, "search")
    builder.add_edge("search", "draft")
    builder.add_edge("draft", END)
    return builder.compile()
