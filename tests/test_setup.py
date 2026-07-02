"""Verify Phase 0 setup: imports work and config raises on missing keys."""
import pytest
from linkedin_agent.config import (
    PROJECT_ROOT,
    getenv_or_raise,
    get_gemini_api_key,
    get_tavily_api_key,
)


def test_project_root():
    assert PROJECT_ROOT.exists()
    assert (PROJECT_ROOT / "src").exists()


def test_getenv_or_raise_missing():
    with pytest.raises(ValueError, match="NOT_SET is not set"):
        getenv_or_raise("NOT_SET")


def test_gemini_key_raises_when_not_set():
    with pytest.raises(ValueError, match="GEMINI_API_KEY is not set"):
        get_gemini_api_key()


def test_tavily_key_raises_when_not_set():
    with pytest.raises(ValueError, match="TAVILY_API_KEY is not set"):
        get_tavily_api_key()


def test_langgraph_importable():
    import langgraph.graph
    assert hasattr(langgraph.graph, "StateGraph")


def test_tavily_importable():
    from tavily import TavilyClient
    assert TavilyClient


def test_genai_importable():
    from langchain_google_genai import ChatGoogleGenerativeAI
    assert ChatGoogleGenerativeAI
