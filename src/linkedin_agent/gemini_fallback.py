import logging

from langchain_google_genai import ChatGoogleGenerativeAI

from linkedin_agent.config import get_gemini_api_key

logger = logging.getLogger(__name__)

PRIMARY_MODEL = "gemini-3.5-flash"
FALLBACK_MODEL = "gemini-3.1-flash-lite"


def create_gemini_llm() -> ChatGoogleGenerativeAI:
    primary = ChatGoogleGenerativeAI(
        model=PRIMARY_MODEL,
        api_key=get_gemini_api_key(),
        timeout=30,
    )
    fallback = ChatGoogleGenerativeAI(
        model=FALLBACK_MODEL,
        api_key=get_gemini_api_key(),
        timeout=60,
    )
    return primary.with_fallbacks([fallback])
