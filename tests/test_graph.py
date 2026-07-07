from unittest.mock import patch

import pytest
from langgraph.graph.state import CompiledStateGraph

from linkedin_agent.graph import GraphState, build_graph


def test_graph_state_type():
    state: GraphState = {
        "topic": "test topic",
        "search_results": "some results",
        "draft": None,
    }
    assert state["topic"] == "test topic"
    assert state["draft"] is None


def test_build_graph_returns_compiled_graph():
    graph = build_graph()
    assert isinstance(graph, CompiledStateGraph)


def test_graph_nodes_exist():
    graph = build_graph()
    nodes = list(graph.nodes.keys())
    assert "search" in nodes
    assert "draft" in nodes


@pytest.mark.skip(reason="Requires real API keys in .env")
def test_search_node_integration():
    from linkedin_agent.nodes.search_node import search_node

    result = search_node({"topic": "LangGraph vs CrewAI comparison 2026"})
    assert "search_results" in result
    assert len(result["search_results"]) > 50


@pytest.mark.skip(reason="Requires real API keys in .env")
def test_draft_node_integration():
    from linkedin_agent.nodes.draft_node import draft_node

    result = draft_node({
        "topic": "switching embedding models due to API rate limits",
        "search_results": "Many teams are moving from OpenAI embeddings to open-source alternatives like BGE or Voyage due to cost and rate limits.",
    })
    assert "draft" in result
    assert len(result["draft"]) > 50


@pytest.mark.skip(reason="Requires real API keys in .env")
def test_graph_end_to_end():
    graph = build_graph()
    result = graph.invoke({"topic": "benefits of local-first AI development"})
    assert result["draft"] is not None
    assert len(result["draft"]) > 100


def test_search_node_mocked():
    mock_response = {
        "answer": "LangGraph is a state graph framework for LLM applications.",
        "results": [
            {
                "content": "LangGraph allows building complex agent workflows.",
                "url": "https://example.com/langgraph",
            }
        ],
    }

    with patch("tavily.TavilyClient") as mock_client:
        instance = mock_client.return_value
        instance.search.return_value = mock_response

        from linkedin_agent.nodes.search_node import search_node

        result = search_node({"topic": "LangGraph"})

    assert "search_results" in result
    assert "LangGraph" in result["search_results"]
    instance.search.assert_called_once_with(
        query="LangGraph",
        search_depth="advanced",
        max_results=5,
        include_answer=True,
    )


def test_draft_node_mocked():
    with (
        patch("langchain_google_genai.ChatGoogleGenerativeAI") as mock_llm,
    ):
        instance = mock_llm.return_value
        instance.invoke.return_value.content = "This is a test draft."

        from linkedin_agent.nodes.draft_node import draft_node

        result = draft_node({
            "topic": "test topic",
            "search_results": "test search results",
        })

    assert result["draft"] == "This is a test draft."
