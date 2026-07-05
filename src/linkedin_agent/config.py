import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PROJECT_ROOT / ".env")


def getenv_or_raise(key: str) -> str:
    value = os.getenv(key)
    if not value:
        raise ValueError(
            f"{key} is not set. "
            f"Copy .env.example to .env and fill in your {key}."
        )
    return value


def getenv_or_default(key: str, default: str = "") -> str:
    return os.getenv(key, default)


def get_gemini_api_key() -> str:
    return getenv_or_raise("GEMINI_API_KEY")


def get_tavily_api_key() -> str:
    return getenv_or_raise("TAVILY_API_KEY")


# --- Phase 2+3: Ideation ---

def get_mongodb_uri() -> str:
    return getenv_or_raise("MONGODB_URI")


def get_mongodb_database() -> str:
    return getenv_or_default("MONGODB_DATABASE", "linkedin_agent")


def get_niche_keywords() -> str:
    return getenv_or_default("NICHE_KEYWORDS", "AI, RAG, LLM, SaaS, automation")


def get_reddit_subreddits() -> list[str]:
    raw = getenv_or_default("REDDIT_SUBREDDITS", "SaaS, artificial, LocalLLaMA")
    return [s.strip() for s in raw.split(",") if s.strip()]


def get_github_topics() -> list[str]:
    raw = getenv_or_default("GITHUB_TOPICS", "rag,llm,ai-agents")
    return [s.strip() for s in raw.split(",") if s.strip()]


def get_github_token() -> str | None:
    return os.getenv("GITHUB_TOKEN") or None


def get_hits_per_source() -> int:
    return int(getenv_or_default("HITS_PER_SOURCE", "10"))


def get_min_reddit_comments() -> int:
    return int(getenv_or_default("MIN_REDDIT_COMMENTS", "5"))


def get_min_hn_points() -> int:
    return int(getenv_or_default("MIN_HN_POINTS", "10"))


def get_min_github_stars() -> int:
    return int(getenv_or_default("MIN_GITHUB_STARS", "100"))
