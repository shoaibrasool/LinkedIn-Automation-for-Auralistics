import json
import threading
import time
from datetime import datetime, timezone
from typing import Annotated, Any, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from tavily import TavilyClient

from linkedin_agent.config import get_niche_keywords, get_tavily_api_key
from linkedin_agent.gemini_fallback import create_gemini_llm
from linkedin_agent.ideation.signals import (
    extract_keywords_from_signals,
    gather_signals,
    format_signals_for_prompt,
)
from linkedin_agent.ideation.trend_discovery import discover_trends
from linkedin_agent.prompts.ideation_prompt import (
    IDEATION_HUMAN_TEMPLATE,
    IDEATION_SYSTEM_PROMPT,
)
from linkedin_agent.scoring.scoring_node import score_ideas_node
from linkedin_agent.storage.supabase_client import SupabaseClient

IDEAS_COLLECTION = "ideas"

_thread_local = threading.local()


def _set_progress_callback(cb):
    _thread_local.progress_callback = cb


def _get_progress_callback():
    return getattr(_thread_local, 'progress_callback', None)


def _reduce_list(left: list[str], right: list[str]) -> list[str]:
    return left + right


class IdeationState(TypedDict):
    niche_keywords: str
    trending_keywords: str
    trending_context: str
    research_context: Annotated[list[str], _reduce_list]
    aggregated_context: str
    generated_ideas_raw: str
    generated_ideas: list[dict]
    saved_ids: list[str]
    scored_ids: list[str]


# ---------------------------------------------------------------------------
# Node 0: Trend discovery — what's trending RIGHT NOW
# ---------------------------------------------------------------------------

def discover_trends_node(state: IdeationState) -> dict:
    cb = _get_progress_callback()
    if cb:
        cb("trend_discovery", "Scanning trending topics...", 5)
    result = discover_trends()
    trending_kw = result.get("trending_keywords", "")
    trending_ctx = result.get("trending_context", "")

    # Merge with static keywords as fallback
    static_kw = state.get("niche_keywords", "")
    merged_kw = trending_kw if trending_kw else static_kw

    cb = _get_progress_callback()
    if cb:
        cb("trend_discovery_done", f"Found trending topics: {merged_kw[:80]}...", 10)
    return {
        "trending_keywords": merged_kw,
        "trending_context": trending_ctx,
    }


# ---------------------------------------------------------------------------
# Node 1a: Tavily web research — now uses TRENDING keywords
# ---------------------------------------------------------------------------

def research_web_node(state: IdeationState) -> dict:
    cb = _get_progress_callback()
    if cb:
        cb("web_research", "Fetching web research via Tavily...", 15)
    query = state.get("trending_keywords") or state["niche_keywords"]
    api_key = get_tavily_api_key()
    client = TavilyClient(api_key=api_key)
    response = client.search(
        query=query,
        search_depth="advanced",
        max_results=8,
        include_answer=True,
    )
    snippets = []
    if answer := response.get("answer"):
        snippets.append(f"[Tavily Summary]: {answer}")
    for result in response.get("results", []):
        content = result.get("content", "")
        url = result.get("url", "")
        if content:
            snippets.append(f"[Web: {url}]: {content[:500]}")
    cb = _get_progress_callback()
    if cb:
        cb("web_research_done", f"Got {len(snippets)} web research items", 22)
    return {"research_context": ["\n\n".join(snippets)] if snippets else []}


# ---------------------------------------------------------------------------
# Node 1b: Signal scrapers (Reddit + HN + GitHub)
# ---------------------------------------------------------------------------

def research_signals_node(state: IdeationState) -> dict:
    cb = _get_progress_callback()
    if cb:
        cb("signals", "Scraping Reddit, HN, and GitHub...", 25)
    trending_kw = state.get("trending_keywords", "")
    signals = gather_signals(trending_keywords=trending_kw)
    formatted = format_signals_for_prompt(signals)

    # Extract novel keywords from signals for broader discovery
    signal_keywords = extract_keywords_from_signals(signals)
    if signal_keywords:
        formatted = (
            f"SIGNAL-DERIVED KEYWORDS (auto-extracted from live signals):\n{signal_keywords}\n\n"
            + formatted
        )

    cb = _get_progress_callback()
    if cb:
        cb("signals_done", "Signal scraping complete", 40)
    if formatted.strip():
        return {"research_context": [formatted]}
    return {"research_context": []}


# ---------------------------------------------------------------------------
# Node 2: Aggregate context
# ---------------------------------------------------------------------------

def aggregate_context_node(state: IdeationState) -> dict:
    cb = _get_progress_callback()
    if cb:
        cb("aggregate", "Combining research context...", 50)
    combined = "\n\n=====\n\n".join(state.get("research_context", []))
    if cb:
        cb("aggregate_done", "Research context aggregated", 55)
    return {"aggregated_context": combined}


# ---------------------------------------------------------------------------
# Node 3: Generate ideas via Gemini
# ---------------------------------------------------------------------------

def generate_ideas_node(state: IdeationState) -> dict:
    cb = _get_progress_callback()
    llm = create_gemini_llm()

    current_date = datetime.now(timezone.utc).strftime("%B %d, %Y")
    keywords = state.get("trending_keywords") or state["niche_keywords"]

    human_text = IDEATION_HUMAN_TEMPLATE.format(
        current_date=current_date,
        keywords=keywords,
        research_context=state["aggregated_context"],
        trending_context=state.get("trending_context", "") or "No trending context available.",
    )

    for attempt in range(3):
        if cb:
            cb("generating", f"Generating ideas via LLM (attempt {attempt + 1}/3)...", 55 + attempt * 5)
        try:
            messages = [
                SystemMessage(content=IDEATION_SYSTEM_PROMPT),
                HumanMessage(content=human_text),
            ]
            response = llm.invoke(messages)
            raw = response.content
            if isinstance(raw, list):
                raw = "".join(
                    part.get("text", "") for part in raw if isinstance(part, dict)
                )
            raw = raw.strip()

            if raw.startswith("```"):
                raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```")

            ideas = json.loads(raw)
            if isinstance(ideas, dict):
                ideas = [ideas]
            if not isinstance(ideas, list) or len(ideas) < 1:
                raise ValueError("Response is not a list of ideas")

            if cb:
                cb("generating_done", f"{len(ideas)} ideas generated", 65)
            for idea in ideas:
                idea.setdefault("source", "generated")
                idea.setdefault("status", "new")
                idea.setdefault("source_signals", [])
                idea.setdefault("created_at", datetime.now(timezone.utc).isoformat())
                idea.setdefault("framework", "Story")
                idea.setdefault("score", 0.5)

            return {"generated_ideas_raw": raw, "generated_ideas": ideas}

        except (json.JSONDecodeError, ValueError):
            if attempt < 2:
                time.sleep(1)
                continue
            return {"generated_ideas_raw": "", "generated_ideas": []}
        except Exception:
            if attempt < 2:
                time.sleep(1)
                continue
            return {"generated_ideas_raw": "", "generated_ideas": []}


# ---------------------------------------------------------------------------
# Node 4: Save ideas (with dedup)
# ---------------------------------------------------------------------------

def save_ideas_node(state: IdeationState) -> dict:
    cb = _get_progress_callback()
    ideas = state.get("generated_ideas", [])
    if not ideas:
        if cb:
            cb("saving_done", "No ideas to save", 80)
        return {"saved_ids": []}

    if cb:
        cb("saving", f"Deduplicating and saving {len(ideas)} ideas...", 75)

    client = SupabaseClient()
    saved_ids: list[str] = []

    existing = client.find(IDEAS_COLLECTION, {}, limit=500)
    existing_titles = {doc.get("generated_idea", "").lower().strip() for doc in existing}

    to_insert = []
    for idea in ideas:
        title = (idea.get("generated_idea") or "").lower().strip()
        if not title:
            continue
        if title in existing_titles:
            continue
        if any(existing_title.startswith(title[:40]) for existing_title in existing_titles):
            continue
        to_insert.append(idea)

    if to_insert:
        saved_ids = client.insert_many(IDEAS_COLLECTION, to_insert)

    if cb:
        cb("saving_done", f"Saved {len(saved_ids)} new ideas ({len(ideas) - len(saved_ids)} duplicates skipped)", 85)

    return {"saved_ids": saved_ids}


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

def build_ideation_graph() -> StateGraph:
    builder = StateGraph(IdeationState)

    builder.add_node("discover_trends", discover_trends_node)
    builder.add_node("research_web", research_web_node)
    builder.add_node("research_signals", research_signals_node)
    builder.add_node("aggregate_context", aggregate_context_node)
    builder.add_node("generate_ideas", generate_ideas_node)
    builder.add_node("save_ideas", save_ideas_node)
    builder.add_node("score_ideas", score_ideas_node)

    builder.add_edge(START, "discover_trends")
    builder.add_edge("discover_trends", "research_web")
    builder.add_edge("discover_trends", "research_signals")
    builder.add_edge("research_web", "aggregate_context")
    builder.add_edge("research_signals", "aggregate_context")
    builder.add_edge("aggregate_context", "generate_ideas")
    builder.add_edge("generate_ideas", "save_ideas")
    builder.add_edge("save_ideas", "score_ideas")
    builder.add_edge("score_ideas", END)

    return builder.compile()


def run_ideation(keywords: str | None = None, progress_callback=None) -> dict[str, Any]:
    if not keywords:
        keywords = get_niche_keywords()

    _set_progress_callback(progress_callback)
    graph = build_ideation_graph()

    initial_state: IdeationState = {
        "niche_keywords": keywords,
        "trending_keywords": "",
        "trending_context": "",
        "research_context": [],
        "aggregated_context": "",
        "generated_ideas_raw": "",
        "generated_ideas": [],
        "saved_ids": [],
        "scored_ids": [],
    }
    try:
        return graph.invoke(initial_state)
    finally:
        _set_progress_callback(None)
