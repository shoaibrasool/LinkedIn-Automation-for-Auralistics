"""Trend discovery module.

Runs parallel Tavily searches for what's trending RIGHT NOW,
extracts keywords, and returns them to replace static NICHE_KEYWORDS.
"""
import logging
import re
from datetime import datetime, timezone
from typing import Any

from tavily import TavilyClient

from linkedin_agent.config import get_tavily_api_key

logger = logging.getLogger(__name__)

TREND_QUERIES = [
    "trending topics in technology this week",
    "what developers and founders are talking about right now",
    "breakout AI tech news past 48 hours",
]

EXCLUDE_PATTERNS = re.compile(
    r"(claude 3\b|gpt-4\b|gpt-3\b|llama 2\b|bart\b|t5\b|bert\b)",
    re.IGNORECASE,
)


def discover_trends() -> dict[str, Any]:
    """Run 3 parallel Tavily searches and return trending keywords + context.

    Returns:
        dict with:
            - trending_keywords: comma-separated extracted keywords
            - trending_context: formatted string of all search snippets
            - trend_summary: single-paragraph summary of what's trending
    """
    api_key = get_tavily_api_key()
    client = TavilyClient(api_key=api_key)

    all_snippets: list[str] = []
    all_keywords: list[str] = []

    for query in TREND_QUERIES:
        try:
            response = client.search(
                query=query,
                search_depth="advanced",
                max_results=5,
                include_answer=True,
            )
            if answer := response.get("answer"):
                all_snippets.append(f"[Trend Summary for '{query}']: {answer}")
                extracted = _extract_keywords(answer)
                all_keywords.extend(extracted)

            for result in response.get("results", []):
                content = result.get("content", "")
                url = result.get("url", "")
                title = result.get("title", "")
                if content and not EXCLUDE_PATTERNS.search(content):
                    all_snippets.append(f"[Trend: {title}]({url}): {content[:500]}")
                    extracted = _extract_keywords(content)
                    all_keywords.extend(extracted)

        except Exception as e:
            logger.warning("Trend query '%s' failed: %s", query, e)
            continue

    # Deduplicate keywords, filter out noise
    seen: set[str] = set()
    clean_keywords: list[str] = []
    for kw in all_keywords:
        low = kw.lower().strip()
        if low not in seen and len(kw) > 2:
            seen.add(low)
            clean_keywords.append(kw)

    trending_str = ", ".join(clean_keywords[:20]) if clean_keywords else ""
    context_str = "\n\n".join(all_snippets) if all_snippets else ""

    logger.info(
        "Discovered %d trending keywords from %d trend queries",
        len(clean_keywords), len(TREND_QUERIES),
    )

    return {
        "trending_keywords": trending_str,
        "trending_context": context_str,
    }


def _extract_keywords(text: str) -> list[str]:
    """Extract noun-phrase-like keywords from text.

    Simple heuristic: grab runs of capitalized words and
    tech-adjacent terms.
    """
    if not text:
        return []

    keywords: list[str] = []

    # Match multi-word capitalized phrases (e.g. "Llama 4", "Claude Sonnet",
    # "Agentic Workflows", "Vector Search")
    phrases = re.findall(r"([A-Z][a-z]+(?:\s+[A-Z]?[a-z0-9]+){0,3})", text)
    keywords.extend(phrases)

    # Also grab specific tech terms: anything with numbers or known suffixes
    tech_terms = re.findall(
        r"\b([A-Za-z]+(?:\s+\d+(?:\.\d+)?)?(?:\s+(?:API|SDK|LLM|RAG|Agent|Framework|Model|Benchmark|Dataset))?)\b",
        text,
    )
    keywords.extend([t for t in tech_terms if len(t) > 3])

    # Filter: remove duplicates, short words, and common noise words
    stop_words = {
        "this", "that", "what", "with", "from", "they", "have", "been",
        "trend", "news", "topic", "week", "today", "just", "about",
        "will", "your", "more", "some", "them", "than", "into",
    }
    filtered = []
    for kw in keywords:
        clean = kw.strip().rstrip(".,!?:;")
        if len(clean) < 4:
            continue
        if clean.lower() in stop_words:
            continue
        filtered.append(clean)

    return filtered
