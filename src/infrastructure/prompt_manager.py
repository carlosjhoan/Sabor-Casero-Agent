"""
Prompt template manager with Langfuse Prompt Management and file-based fallback.

Usage:
    from src.infrastructure.prompt_manager import get_prompt_manager
    from src.config.environment import settings

    prompt = get_prompt_manager(settings.prompt_fallback_map).get(
        "classifier",
        message=user_message,
        docs_summaries=docs,
        summary_order=summary_order,
        summary_conversation=summary_conversation,
    )
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class PromptManager:
    """Centralized prompt template manager.

    Tries Langfuse Prompt Management first (via get_prompt + compile).
    Falls back to file-based prompts via build_prompt().
    Gracefully degrades — if Langfuse is down/unconfigured, files work.
    """

    def __init__(self, fallback_map: dict[str, str] = None) -> None:
        """Initialize PromptManager.

        Args:
            fallback_map: Mapping of prompt name → file path for file fallback.
        """
        self._fallback_map = fallback_map or {}
        self._langfuse = None
        self._langfuse_available = False
        self._init_langfuse()

    def _init_langfuse(self) -> None:
        """Initialize Langfuse client from settings. Wrap in try/except.

        Reads credentials from ``settings`` (pydantic-settings loads from
        ``.env``) and propagates them to ``os.environ`` so Langfuse SDK
        can find them.
        """
        import os as _os

        try:
            from src.config.environment import settings

            env_key = settings.langfuse_public_key
            env_secret = settings.langfuse_secret_key
            env_host = settings.langfuse_host
        except Exception:
            env_key = env_secret = None
            env_host = "https://us.cloud.langfuse.com"

        if not env_key:
            logger.info(
                "Langfuse not configured — using file-based prompts"
            )
            return

        # Propagate to os.environ so Langfuse() can read them
        _os.environ.setdefault("LANGFUSE_PUBLIC_KEY", env_key)
        _os.environ.setdefault("LANGFUSE_SECRET_KEY", env_secret or "")
        _os.environ.setdefault("LANGFUSE_HOST", env_host)

        try:
            from langfuse import Langfuse

            self._langfuse = Langfuse()
            self._langfuse_available = True
            logger.info("Langfuse Prompt Management initialized successfully")
        except Exception as e:
            self._langfuse = None
            self._langfuse_available = False
            logger.warning(
                "Langfuse not available — using file-based prompts. Error: %s", e
            )

    def get(self, name: str, **variables) -> str:
        """Get rendered prompt by name.

        1. Tries langfuse.get_prompt(name).compile(**variables)
        2. On failure: falls back to build_prompt(fallback_map[name], **variables)
        3. If no fallback path: raises ValueError

        Args:
            name: Prompt name in Langfuse (and key in fallback_map).
            **variables: Template variables to render into the prompt.

        Returns:
            Rendered prompt string.

        Raises:
            ValueError: If no fallback path is configured for the given name.
        """
        # 1. Try Langfuse
        if self._langfuse_available and self._langfuse is not None:
            try:
                prompt = self._langfuse.get_prompt(name)
                if prompt is not None:
                    rendered = prompt.compile(**variables)
                    logger.debug("Loaded prompt '%s' from Langfuse", name)
                    return rendered
                else:
                    logger.debug(
                        "Prompt '%s' not found in Langfuse, falling back to file",
                        name,
                    )
            except Exception as e:
                logger.debug(
                    "Langfuse get_prompt('%s') failed: %s — falling back to file",
                    name,
                    e,
                )

        # 2. Fall back to file
        if name not in self._fallback_map:
            raise ValueError(
                f"No fallback path configured for prompt '{name}'. "
                f"Available prompts: {list(self._fallback_map.keys())}"
            )

        from src.utils.utils import build_prompt

        file_path = self._fallback_map[name]
        logger.debug("Loading prompt '%s' from file: %s", name, file_path)
        return build_prompt(file_path, **variables)


# Module-level singleton
_prompt_manager: Optional[PromptManager] = None


def get_prompt_manager(fallback_map: dict[str, str] = None) -> PromptManager:
    """Get or create the PromptManager singleton.

    Args:
        fallback_map: Mapping of prompt name → file path. Only used on first call.

    Returns:
        PromptManager instance.
    """
    global _prompt_manager
    if _prompt_manager is None:
        _prompt_manager = PromptManager(fallback_map=fallback_map)
    return _prompt_manager
