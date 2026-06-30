"""
LLM client — LiteLLM powered.

Provides backward-compatible exports so existing consumers don't need import changes.
"""
from .litellm_client import LiteLLMClient

# Backward-compatible alias — consumers use LLMClient in type hints and mocks
LLMClient = LiteLLMClient


def get_llm_client_for_stage(stage: str = "default") -> LiteLLMClient:
    """
    Create a LiteLLM client.

    Args:
        stage: Stage name (classifier, retriever, etc.) — kept for future
               per-stage config (rate limits, timeouts, API keys).

    Returns:
        LiteLLMClient instance
    """
    return LiteLLMClient()


def get_model_for_stage(stage: str, settings) -> str:
    """Get the LiteLLM model string for a given stage."""
    stage_model_map = {
        "classifier": settings.llm_model_classifier,
        "retriever": settings.llm_model_retriever,
        "summarizer": settings.llm_model_summarizer,
        "response": settings.llm_model_response,
    }
    return stage_model_map.get(stage, "deepseek/deepseek-v4-flash")
