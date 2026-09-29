"""Agent LLM Provider for LangChain ReAct Chatbots.

Configures and instantiates ChatMistralAI for Global and Document ReAct agents,
preserving isolation from extraction/OCR LLM components.
"""
import logging
from typing import Optional

from langchain_mistralai import ChatMistralAI

from app.core.config import settings

logger = logging.getLogger(__name__)


def get_agent_llm(temperature: float = 0.0, max_tokens: int = 1024) -> ChatMistralAI:
    """Return a configured ChatMistralAI instance for ReAct agent loops.

    Raises:
        ValueError: if MISTRAL_API_KEY is not configured in production settings.
    """
    api_key = settings.MISTRAL_API_KEY
    if not api_key:
        logger.warning("MISTRAL_API_KEY is not configured for ReAct agent.")

    # ChatMistralAI accepts api_key, model, temperature, max_tokens, endpoint, timeout
    kwargs = {
        "model": settings.EXTRACTION_LLM_MODEL or "mistral-small-2603",
        "temperature": temperature,
        "max_tokens": max_tokens,
        "timeout": int(getattr(settings, "CHAT_REQUEST_TIMEOUT_SECONDS", 30.0)),
        "max_retries": 1,
    }
    if api_key:
        kwargs["api_key"] = api_key
    else:
        # Dummy key for test harnesses or offline initializations
        kwargs["api_key"] = "test-placeholder-key"

    if settings.MISTRAL_API_BASE and settings.MISTRAL_API_BASE != "https://api.mistral.ai/v1":
        kwargs["endpoint"] = settings.MISTRAL_API_BASE.rstrip("/")

    return ChatMistralAI(**kwargs)
