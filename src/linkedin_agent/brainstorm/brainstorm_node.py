import json
import logging
import time
from datetime import datetime, timezone

from langchain_core.messages import HumanMessage, SystemMessage

from linkedin_agent.gemini_fallback import create_gemini_llm

logger = logging.getLogger(__name__)

BRAINSTORM_SYSTEM_PROMPT = (
    "You are an expert LinkedIn content strategist. Your job is to take a single scored idea "
    "and generate 15-20 distinct angles for a LinkedIn post.\n\n"
    "GROUNDING RULES:\n"
    "- FRESH CONTEXT from the web is provided below. Every angle must reference specifics from "
    "the fresh search results or the original idea — do not fabricate details.\n"
    "- The current date is {current_date}. Do NOT generate angles about stale topics "
    "(e.g., Claude 3.5, GPT-4, Llama 2 — these are old). Angles must feel current.\n\n"
    "TOPIC DIVERSITY:\n"
    "- Your 15-20 angles should cover at least 4 different sub-topics or angles of attack.\n"
    "- Do NOT generate more than 3 angles on the same narrow sub-topic.\n"
    "- Spread across different categories (see below) to ensure real variety.\n\n"
    "Each angle must have a DIFFERENT hook and stance. Demand REAL structural variety — "
    "do NOT reword the same sentence 15 times. Include angles from at least 6 of these categories:\n"
    "1. CONTRARIAN — Push back against a popular opinion\n"
    "2. TUTORIAL — Teach something step-by-step\n"
    "3. VULNERABLE — Share a personal failure or insecurity\n"
    "4. DATA-DRIVEN — Lead with a number, benchmark, or finding\n"
    "5. QUESTION-BASED — Open with a provocative question\n"
    "6. HOT-TAKE — Strong, opinionated stance\n"
    "7. STORY/ANECDOTE — Narrative-driven, personal experience\n"
    "8. COMPARISON — X vs Y, before/after\n"
    "9. PREDICTION — Where is this going?\n"
    "10. LISTICLE — X lessons / Y things I learned\n\n"
    "Return a JSON array of objects. Each object has:\n"
    '  "hook": <the 1-2 line hook that opens the post>,\n'
    '  "premise": <one-sentence summary of the post>,\n'
    '  "stance": <category label from the list above>,\n'
    '  "source_url": <URL from the fresh search results that this angle references, or "">,\n'
    '  "source_platform": <"tavily" or "original_idea">\n\n'
    "Output ONLY the JSON array. No preamble, no explanation, no markdown fences."
)

BRAINSTORM_HUMAN_TEMPLATE = (
    "Current date: {current_date}\n\n"
    "Here is the scored idea:\n\n"
    "Idea: {idea_text}\n"
    "Hook: {hook}\n"
    "Original scores — originality: {originality}, value_to_reader: {value_to_reader}, "
    "authority_fit: {authority_fit}, icp_relevance: {icp_relevance}, sales_potential: {sales_potential}\n"
    "Reasoning: {reasoning}\n\n"
    "FRESH WEB SEARCH RESULTS (live context for this topic):\n{research_context}\n\n"
    "Generate 15-20 distinct angles for this idea. Each angle must have a different hook and stance. "
    "Be creative — the goal is to find the angle the founder wouldn't have thought of first. "
    "Ground your angles in the FRESH WEB SEARCH RESULTS above — reference real, current details. "
    "Spread across at least 4 different sub-topics. Include the source_url for each angle "
    "(from the search results) so we can trace it back."
)


def brainstorm_node(scored_idea: dict, research_context: str = "") -> dict:
    idea_text = scored_idea.get("generated_idea", "") or ""
    if not idea_text.strip():
        logger.warning("Empty idea text, skipping brainstorm")
        return {"angles": []}

    llm = create_gemini_llm()
    current_date = datetime.now(timezone.utc).strftime("%B %d, %Y")

    system_text = BRAINSTORM_SYSTEM_PROMPT.format(current_date=current_date)

    human_text = BRAINSTORM_HUMAN_TEMPLATE.format(
        current_date=current_date,
        idea_text=idea_text,
        hook=scored_idea.get("hook", ""),
        originality=scored_idea.get("originality", "?"),
        value_to_reader=scored_idea.get("value_to_reader", "?"),
        authority_fit=scored_idea.get("authority_fit", "?"),
        icp_relevance=scored_idea.get("icp_relevance", "?"),
        sales_potential=scored_idea.get("sales_potential", "?"),
        reasoning=scored_idea.get("scoring_reasoning", ""),
        research_context=research_context or "No fresh web results found.",
    )

    for attempt in range(3):
        try:
            messages = [
                SystemMessage(content=system_text),
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

            angles = json.loads(raw)
            if isinstance(angles, dict):
                angles = [angles]
            if not isinstance(angles, list) or len(angles) < 3:
                raise ValueError(f"Expected at least 3 angles, got {len(angles)}")

            for angle in angles:
                angle.setdefault("hook", "")
                angle.setdefault("premise", "")
                angle.setdefault("stance", "general")
                angle.setdefault("source_url", "")
                angle.setdefault("source_platform", "original_idea")

            logger.info(
                "Generated %d angles for idea '%s'",
                len(angles), idea_text[:60],
            )
            return {"angles": angles}

        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("Attempt %d/3 failed (parse): %s", attempt + 1, e)
            if attempt < 2:
                time.sleep(1)
                continue
            logger.error("Failed to generate angles after 3 attempts")
            return {"angles": []}
        except Exception as e:
            logger.error("Attempt %d/3 failed (API): %s", attempt + 1, e)
            if attempt < 2:
                time.sleep(1)
                continue
            return {"angles": []}
