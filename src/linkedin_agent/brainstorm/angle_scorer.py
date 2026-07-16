import json
import logging
import time
from datetime import datetime, timezone

from openai import OpenAI

from linkedin_agent.config import get_groq_api_key
from linkedin_agent.scoring.rubric import SCORING_SYSTEM_PROMPT, ScoreCard

logger = logging.getLogger(__name__)

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_MODEL = "llama-3.3-70b-versatile"

ANGLE_SCORING_HUMAN_TEMPLATE = (
    "Current date: {current_date}\n\n"
    "Score the following LinkedIn post angles using the same strict rubric. "
    "Each angle is a separate item to evaluate.\n\n"
    "IMPORTANT: Penalize angles that are about stale topics (e.g., Claude 3.5, GPT-4, Llama 2). "
    "Bonus points for angles tied to CURRENT trends and fresh developments.\n\n"
    "Return a JSON array of objects. Each object must have the fields: "
    "originality, value_to_reader, authority_fit, icp_relevance, sales_potential, reasoning, "
    "and an \"angle_hook\" field matching the hook of the angle being scored.\n\n"
    "Angles:\n{angles_text}"
)


def score_angles(angles: list[dict]) -> list[dict]:
    if not angles:
        return []

    client = OpenAI(api_key=get_groq_api_key(), base_url=GROQ_BASE_URL, timeout=30)

    angles_text = "\n---\n".join(
        f"Angle {i + 1}:\nHook: {a.get('hook', '')}\nPremise: {a.get('premise', '')}\nStance: {a.get('stance', '')}"
        for i, a in enumerate(angles)
    )

    current_date = datetime.now(timezone.utc).strftime("%B %d, %Y")
    human_text = ANGLE_SCORING_HUMAN_TEMPLATE.format(current_date=current_date, angles_text=angles_text)

    for attempt in range(3):
        try:
            response = client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[
                    {"role": "system", "content": SCORING_SYSTEM_PROMPT},
                    {"role": "user", "content": human_text},
                ],
                response_format={"type": "json_object"},
                temperature=0.3,
            )
            raw = response.choices[0].message.content
            if not raw:
                raise ValueError("Empty response from Groq")

            data = json.loads(raw)

            if isinstance(data, dict):
                if "angles" in data:
                    scored_list = data["angles"]
                else:
                    scored_list = [data]
            elif isinstance(data, list):
                scored_list = data
            else:
                raise ValueError(f"Unexpected response shape: {type(data)}")

            hook_to_scores: dict[str, dict] = {}
            for entry in scored_list:
                hook_key = (entry.get("angle_hook") or "").strip().lower()
                if hook_key:
                    hook_to_scores[hook_key] = entry

            scored_angles = []
            for angle in angles:
                hook_key = (angle.get("hook") or "").strip().lower()
                entry = hook_to_scores.get(hook_key)

                if entry:
                    try:
                        score_card = ScoreCard(
                            originality=entry.get("originality", 3),
                            value_to_reader=entry.get("value_to_reader", 3),
                            authority_fit=entry.get("authority_fit", 3),
                            icp_relevance=entry.get("icp_relevance", 3),
                            sales_potential=entry.get("sales_potential", 3),
                            reasoning=entry.get("reasoning", ""),
                        )
                    except Exception:
                        score_card = ScoreCard(
                            originality=3, value_to_reader=3, authority_fit=3,
                            icp_relevance=3, sales_potential=3, reasoning="fallback",
                        )
                else:
                    score_card = ScoreCard(
                        originality=3, value_to_reader=3, authority_fit=3,
                        icp_relevance=3, sales_potential=3, reasoning="unscored",
                    )

                total = (
                    score_card.originality
                    + score_card.value_to_reader
                    + score_card.authority_fit
                    + score_card.icp_relevance
                    + score_card.sales_potential
                )

                scored_angles.append({
                    **angle,
                    "originality": score_card.originality,
                    "value_to_reader": score_card.value_to_reader,
                    "authority_fit": score_card.authority_fit,
                    "icp_relevance": score_card.icp_relevance,
                    "sales_potential": score_card.sales_potential,
                    "scoring_reasoning": score_card.reasoning,
                    "total_score": total,
                    "normalized_score": total / 25.0,
                })

            logger.info("Scored %d angles", len(scored_angles))
            return scored_angles

        except (json.JSONDecodeError, ValueError, TypeError) as e:
            logger.warning("Angle scoring attempt %d/3 failed: %s", attempt + 1, e)
            if attempt < 2:
                time.sleep(1)
                continue

            logger.error("Failed to score angles after 3 attempts, using fallback scores")
            for angle in angles:
                angle.setdefault("total_score", 15)
                angle.setdefault("normalized_score", 0.6)
                angle.setdefault("originality", 3)
                angle.setdefault("value_to_reader", 3)
                angle.setdefault("authority_fit", 3)
                angle.setdefault("icp_relevance", 3)
                angle.setdefault("sales_potential", 3)
                angle.setdefault("scoring_reasoning", "fallback after scoring failure")
            return angles
