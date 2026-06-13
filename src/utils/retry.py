"""
retry_with_backoff — async retry utility for pipeline stages.

Usage:
    result = await retry_with_backoff(
        lambda: some_async_function(arg1, arg2),
        max_retries=2,
        stage_name="classification"
    )
"""
import asyncio
import random
import logging
from typing import Callable, Awaitable, Type, Tuple, Any

logger = logging.getLogger("RAG-Agent")

# Exceptions that trigger a retry
RETRYABLE_EXCEPTIONS: Tuple[Type[BaseException], ...] = (
    TimeoutError,
    ConnectionError,
    asyncio.TimeoutError,
)

# Exceptions that propagate immediately (non-retryable)
NON_RETRYABLE_EXCEPTIONS: Tuple[Type[BaseException], ...] = (
    ValueError,
    TypeError,
    KeyError,
    AttributeError,
)


async def retry_with_backoff(
    fn: Callable[[], Awaitable[Any]],
    max_retries: int = 2,
    base_delay: float = 0.5,
    max_delay: float = 5.0,
    stage_name: str = "unknown",
) -> Any:
    """
    Execute an async callable with exponential backoff retry.

    Retryable exceptions: TimeoutError, ConnectionError, asyncio.TimeoutError.
    Non-retryable exceptions: ValueError, TypeError, KeyError, AttributeError
    propagate immediately without retry.

    Args:
        fn: Async callable with no arguments (use lambda to wrap).
        max_retries: Maximum number of retry attempts (default 2).
        base_delay: Base delay in seconds (default 0.5).
        max_delay: Maximum delay in seconds (default 5.0).
        stage_name: Human-readable stage name for logging.

    Returns:
        The return value of fn() on success.

    Raises:
        NON_RETRYABLE_EXCEPTIONS: Propagate immediately without retry.
        RETRYABLE_EXCEPTIONS: After exhausting max_retries attempts.
    """
    last_exception = None

    for attempt in range(max_retries + 1):
        try:
            return await fn()
        except NON_RETRYABLE_EXCEPTIONS:
            raise
        except RETRYABLE_EXCEPTIONS as e:
            last_exception = e
            if attempt < max_retries:
                delay = min(base_delay * (2 ** attempt), max_delay)
                jitter = random.uniform(0, delay * 0.25)
                sleep_time = delay + jitter
                logger.warning(
                    f"Retry {attempt + 1}/{max_retries} for stage '{stage_name}' "
                    f"after {sleep_time:.2f}s: {e}"
                )
                await asyncio.sleep(sleep_time)
            else:
                logger.error(
                    f"All {max_retries} retries exhausted for stage "
                    f"'{stage_name}': {e}"
                )
        except Exception as e:
            # Catch-all for unexpected exceptions — still retry
            last_exception = e
            if attempt < max_retries:
                delay = min(base_delay * (2 ** attempt), max_delay)
                jitter = random.uniform(0, delay * 0.25)
                sleep_time = delay + jitter
                logger.warning(
                    f"Retry {attempt + 1}/{max_retries} for stage '{stage_name}' "
                    f"after {sleep_time:.2f}s (unexpected): {e}"
                )
                await asyncio.sleep(sleep_time)
            else:
                logger.error(
                    f"All {max_retries} retries exhausted for stage "
                    f"'{stage_name}' (unexpected): {e}"
                )

    raise last_exception


# Per-stage retry configuration
STAGE_RETRY_CONFIG: dict = {
    "input_guard": {"max_retries": 1, "base_delay": 0.5},
    "classification": {"max_retries": 2, "base_delay": 0.5},
    "rag": {"max_retries": 0, "base_delay": 0.5},
    "order_processing": {"max_retries": 1, "base_delay": 0.5},
    "response": {"max_retries": 2, "base_delay": 0.5},
    "logging": {"max_retries": 0, "base_delay": 0.5},
    "summarization": {"max_retries": 0, "base_delay": 0.5},
}
