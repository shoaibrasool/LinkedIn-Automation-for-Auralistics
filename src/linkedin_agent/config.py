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


def get_gemini_api_key() -> str:
    return getenv_or_raise("GEMINI_API_KEY")


def get_tavily_api_key() -> str:
    return getenv_or_raise("TAVILY_API_KEY")
