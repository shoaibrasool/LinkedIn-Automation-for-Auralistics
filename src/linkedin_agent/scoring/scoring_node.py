import json
import logging
import threading
import time

from openai import OpenAI

from linkedin_agent.config import get_groq_api_key
from linkedin_agent.scoring.rubric import SCORING_SYSTEM_PROMPT, ScoreCard
from linkedin_agent.storage.supabase_client import SupabaseClient

logger = logging.getLogger(__name__)

IDEAS_COLLECTION = "ideas"
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_MODEL = "llama-3.3-70b-versatile"

_thread_local = threading.local()


def _get_progress_callback():
    return getattr(_thread_local, 'progress_callback', None)


def _score_single_idea(client: OpenAI, idea_text: str) -> ScoreCard | None:
    for attempt in range(3):
        try:
            response = client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[
                    {"role": "system", "content": SCORING_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": f"Score this raw LinkedIn post idea:\n\n{idea_text}",
                    },
                ],
                response_format={"type": "json_object"},
                temperature=0.3,
            )
            raw = response.choices[0].message.content
            if not raw:
                raise ValueError("Empty response from Groq")
            data = json.loads(raw)
            return ScoreCard(**data)
        except (json.JSONDecodeError, ValueError, TypeError):
            if attempt < 2:
                time.sleep(1)
                continue
            return None


def score_ideas_node(state: dict) -> dict:
    cb = _get_progress_callback()
    supabase = SupabaseClient()
    ideas = supabase.find(
        IDEAS_COLLECTION,
        filter={"status": "new"},
        sort=[("created_at", -1)],
        limit=50,
    )

    if not ideas:
        if cb:
            cb("scoring_done", "No new ideas to score", 100)
        return {"scored_ids": []}

    client = OpenAI(api_key=get_groq_api_key(), base_url=GROQ_BASE_URL, timeout=30)
    scored_ids: list[str] = []

    for idx, idea in enumerate(ideas):
        idea_text = idea.get("generated_idea", "") or ""
        if not idea_text.strip():
            continue

        if cb:
            cb("scoring", f"Scoring idea {idx + 1}/{len(ideas)} via Groq LLaMA...", 90 + (idx / max(len(ideas), 1)) * 10)

        score_card = _score_single_idea(client, idea_text)
        if score_card is None:
            continue

        total = (
            score_card.originality
            + score_card.value_to_reader
            + score_card.authority_fit
            + score_card.icp_relevance
            + score_card.sales_potential
        )

        existing_signals = idea.get("source_signals") or []
        scoring_record = {
            "platform": "_scoring",
            "originality": score_card.originality,
            "value_to_reader": score_card.value_to_reader,
            "authority_fit": score_card.authority_fit,
            "icp_relevance": score_card.icp_relevance,
            "sales_potential": score_card.sales_potential,
            "reasoning": score_card.reasoning,
            "total": total,
        }
        existing_signals.append(scoring_record)

        update = {
            "score": total / 25.0,
            "status": "scored",
            "source_signals": existing_signals,
            "originality": score_card.originality,
            "value_to_reader": score_card.value_to_reader,
            "authority_fit": score_card.authority_fit,
            "icp_relevance": score_card.icp_relevance,
            "sales_potential": score_card.sales_potential,
            "scoring_reasoning": score_card.reasoning,
        }
        supabase.update_one(IDEAS_COLLECTION, {"id": idea["id"]}, update)
        scored_ids.append(str(idea["id"]))

        logger.info(
            "Scored idea %s: total=%d/25 normalized=%.2f | orig=%d val=%d auth=%d icp=%d sales=%d",
            idea["id"],
            total,
            total / 25.0,
            score_card.originality,
            score_card.value_to_reader,
            score_card.authority_fit,
            score_card.icp_relevance,
            score_card.sales_potential,
        )

    if cb:
        cb("scoring_done", f"Scored {len(scored_ids)} ideas", 100)

    return {"scored_ids": scored_ids}
