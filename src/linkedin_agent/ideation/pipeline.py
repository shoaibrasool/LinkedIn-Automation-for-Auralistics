import json
import time
from datetime import datetime, timezone
from typing import Annotated, Any, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import END, START, StateGraph
from tavily import TavilyClient

from linkedin_agent.config import get_gemini_api_key, get_niche_keywords, get_tavily_api_key
from linkedin_agent.ideation.signals import gather_signals, format_signals_for_prompt
from linkedin_agent.prompts.ideation_prompt import (
    IDEATION_HUMAN_TEMPLATE,
    IDEATION_SYSTEM_PROMPT,
)
from linkedin_agent.storage.db_client import DBClient

IDEAS_COLLECTION = "ideas"


def _reduce_list(left: list[str], right: list[str]) -> list[str]:
    return left + right


class IdeationState(TypedDict):
    niche_keywords: str
    research_context: Annotated[list[str], _reduce_list]
    aggregated_context: str
    generated_ideas_raw: str
    generated_ideas: list[dict]
    saved_ids: list[str]


# ---------------------------------------------------------------------------
# Node 1a: Tavily web research
# ---------------------------------------------------------------------------

def research_web_node(state: IdeationState) -> dict:
    api_key = get_tavily_api_key()
    client = TavilyClient(api_key=api_key)
    response = client.search(
        query=state["niche_keywords"],
        search_depth="advanced",
        max_results=5,
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
    return {"research_context": ["\n\n".join(snippets)] if snippets else []}


# ---------------------------------------------------------------------------
# Node 1b: Signal scrapers (Reddit + HN + GitHub)
# ---------------------------------------------------------------------------

def research_signals_node(state: IdeationState) -> dict:
    signals = gather_signals()
    formatted = format_signals_for_prompt(signals)
    if formatted.strip():
        return {"research_context": [formatted]}
    return {"research_context": []}


# ---------------------------------------------------------------------------
# Node 2: Aggregate context
# ---------------------------------------------------------------------------

def aggregate_context_node(state: IdeationState) -> dict:
    combined = "\n\n=====\n\n".join(state.get("research_context", []))
    return {"aggregated_context": combined}


# ---------------------------------------------------------------------------
# Node 3: Generate ideas via Gemini
# ---------------------------------------------------------------------------

def generate_ideas_node(state: IdeationState) -> dict:
    llm = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        api_key=get_gemini_api_key(),
        temperature=0.9,
    )

    human_text = IDEATION_HUMAN_TEMPLATE.format(
        keywords=state["niche_keywords"],
        research_context=state["aggregated_context"],
    )

    for attempt in range(3):
        try:
            messages = [
                SystemMessage(content=IDEATION_SYSTEM_PROMPT),
                HumanMessage(content=human_text),
            ]
            response = llm.invoke(messages)
            raw = response.content.strip()

            if raw.startswith("```"):
                raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```")

            ideas = json.loads(raw)
            if isinstance(ideas, dict):
                ideas = [ideas]
            if not isinstance(ideas, list) or len(ideas) < 1:
                raise ValueError("Response is not a list of ideas")

            for idea in ideas:
                idea.setdefault("source", "generated")
                idea.setdefault("status", "new")
                idea.setdefault("source_signals", [])
                idea.setdefault("created_at", datetime.now(timezone.utc).isoformat())
                idea.setdefault("framework", "Story")
                idea.setdefault("score", 0.5)

            return {"generated_ideas_raw": raw, "generated_ideas": ideas}

        except (json.JSONDecodeError, ValueError) as e:
            if attempt < 2:
                time.sleep(1)
                continue
            return {"generated_ideas_raw": "", "generated_ideas": []}


# ---------------------------------------------------------------------------
# Node 4: Save ideas to database (with dedup)
# ---------------------------------------------------------------------------

def save_ideas_node(state: IdeationState) -> dict:
    ideas = state.get("generated_ideas", [])
    if not ideas:
        return {"saved_ids": []}

    db = DBClient()
    saved_ids: list[str] = []

    existing = db.find(IDEAS_COLLECTION, {}, limit=500)
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
        saved_ids = db.insert_many(IDEAS_COLLECTION, to_insert)

    return {"saved_ids": saved_ids}


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

def build_ideation_graph() -> StateGraph:
    builder = StateGraph(IdeationState)

    builder.add_node("research_web", research_web_node)
    builder.add_node("research_signals", research_signals_node)
    builder.add_node("aggregate_context", aggregate_context_node)
    builder.add_node("generate_ideas", generate_ideas_node)
    builder.add_node("save_ideas", save_ideas_node)

    builder.add_edge(START, "research_web")
    builder.add_edge(START, "research_signals")
    builder.add_edge("research_web", "aggregate_context")
    builder.add_edge("research_signals", "aggregate_context")
    builder.add_edge("aggregate_context", "generate_ideas")
    builder.add_edge("generate_ideas", "save_ideas")
    builder.add_edge("save_ideas", END)

    return builder.compile()


def run_ideation(keywords: str | None = None) -> dict[str, Any]:
    if not keywords:
        keywords = get_niche_keywords()

    graph = build_ideation_graph()
    initial_state: IdeationState = {
        "niche_keywords": keywords,
        "research_context": [],
        "aggregated_context": "",
        "generated_ideas_raw": "",
        "generated_ideas": [],
        "saved_ids": [],
    }
    return graph.invoke(initial_state)
