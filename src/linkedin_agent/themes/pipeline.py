import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from openai import OpenAI

from linkedin_agent.config import get_groq_api_key
from linkedin_agent.storage.supabase_client import SupabaseClient
from linkedin_agent.themes.prompts import CLUSTER_HUMAN_TEMPLATE, CLUSTER_SYSTEM_PROMPT

logger = logging.getLogger(__name__)

THEMES_COLLECTION = "weekly_themes"
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_MODEL = "llama-3.3-70b-versatile"

PILLARS = [
    "build_in_public",
    "technical_teardown",
    "trend_commentary",
    "icp_problem_solution",
]


class ThemeState(TypedDict):
    angles: list[dict]
    candidate_themes: list[dict]
    selected_theme: dict | None
    theme_document: dict | None


def cluster_themes_node(state: ThemeState) -> dict:
    angles = state.get("angles", [])
    if not angles:
        logger.warning("No angles provided for theme clustering")
        return {"candidate_themes": []}

    if len(angles) < 3:
        logger.warning("Need at least 3 angles to form a theme, got %d", len(angles))
        return {"candidate_themes": []}

    angles_text = "\n---\n".join(
        f"Angle {i + 1}:\nHook: {a.get('hook', '')}\nPremise: {a.get('premise', '')}\nStance: {a.get('stance', '')}\n"
        f"Score: {a.get('normalized_score', 'N/A')}"
        for i, a in enumerate(angles)
    )

    client = OpenAI(api_key=get_groq_api_key(), base_url=GROQ_BASE_URL)
    human_text = CLUSTER_HUMAN_TEMPLATE.format(angles_text=angles_text)

    for attempt in range(3):
        try:
            response = client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[
                    {"role": "system", "content": CLUSTER_SYSTEM_PROMPT},
                    {"role": "user", "content": human_text},
                ],
                response_format={"type": "json_object"},
                temperature=0.7,
            )
            raw = response.choices[0].message.content
            if not raw:
                raise ValueError("Empty response from Groq")

            if raw.startswith("```"):
                raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```")

            data = json.loads(raw)

            if isinstance(data, dict):
                candidates = data.get("candidates", data.get("themes", None))
                if isinstance(candidates, list):
                    pass
                elif isinstance(data, dict) and any(
                    isinstance(v, list) for v in data.values()
                ):
                    candidates = next(v for v in data.values() if isinstance(v, list))
                else:
                    candidates = [data]
            elif isinstance(data, list):
                candidates = data
            else:
                raise ValueError(f"Unexpected response shape: {type(data)}")

            if not isinstance(candidates, list):
                raise ValueError("Could not extract a list of theme candidates")

            logger.info(
                "Generated %d candidate theme(s) from %d angles",
                len(candidates), len(angles),
            )
            return {"candidate_themes": candidates}

        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("Theme clustering attempt %d/3 failed: %s", attempt + 1, e)
            if attempt < 2:
                time.sleep(1)
                continue
            logger.error("Failed to cluster themes after 3 attempts")
            return {"candidate_themes": []}


def select_theme_node(state: ThemeState) -> dict:
    candidates = state.get("candidate_themes", [])
    if not candidates:
        return {"selected_theme": None, "theme_document": None}

    sorted_candidates = sorted(
        candidates,
        key=lambda c: c.get("coherence_score", 0),
        reverse=True,
    )
    best = sorted_candidates[0]

    pillar_mapping = {}
    for angle_entry in best.get("angles", []):
        pillar = angle_entry.get("pillar", "")
        if pillar in PILLARS:
            pillar_mapping[pillar] = {
                "hook": angle_entry.get("hook", ""),
                "premise": angle_entry.get("premise", ""),
            }

    week_start = _get_monday()
    theme_document = {
        "week_date": week_start.isoformat(),
        "theme_statement": best.get("theme_statement", ""),
        "rationale": best.get("rationale", ""),
        "pillar_mapping": pillar_mapping,
        "status": "selected",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "selected_at": datetime.now(timezone.utc).isoformat(),
        "candidate_themes": candidates,
        "angle_count": len(best.get("angles", [])),
    }

    logger.info(
        "Auto-selected theme: '%s' (coherence: %d/10, %d angles mapped to %d pillars)",
        theme_document["theme_statement"][:80],
        best.get("coherence_score", 0),
        len(best.get("angles", [])),
        len(pillar_mapping),
    )

    return {"selected_theme": best, "theme_document": theme_document}


def save_theme_node(state: ThemeState) -> dict:
    document = state.get("theme_document")
    if not document:
        logger.warning("No theme document to save")
        return {}

    client = SupabaseClient()
    theme_id = client.insert_one(THEMES_COLLECTION, document)
    logger.info(
        "Saved theme '%s' to supabase with id=%s",
        document["theme_statement"][:60], theme_id,
    )
    return {"theme_document": {**document, "id": theme_id}}


def _get_monday():
    today = datetime.now(timezone.utc)
    return today - timedelta(days=today.weekday())


def build_theme_graph() -> StateGraph:
    builder = StateGraph(ThemeState)

    builder.add_node("cluster_themes", cluster_themes_node)
    builder.add_node("select_theme", select_theme_node)
    builder.add_node("save_theme", save_theme_node)

    builder.add_edge(START, "cluster_themes")
    builder.add_edge("cluster_themes", "select_theme")
    builder.add_edge("select_theme", "save_theme")
    builder.add_edge("save_theme", END)

    return builder.compile()


def create_weekly_theme(angles: list[dict]) -> dict[str, Any]:
    graph = build_theme_graph()
    initial_state: ThemeState = {
        "angles": angles,
        "candidate_themes": [],
        "selected_theme": None,
        "theme_document": None,
    }
    result = graph.invoke(initial_state)
    return result.get("theme_document") or {}
