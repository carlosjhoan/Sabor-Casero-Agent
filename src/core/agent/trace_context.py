"""
TraceContext — contextvars-based trace_id, span decorator, and structured event log.

Usage as context manager::

    from src.core.agent.trace_context import span, new_trace_id, get_event_log

    new_trace_id()
    with span("classify"):
        ...  # stage work

    log = get_event_log()  # list of structured event dicts

Usage as decorator::

    from src.core.agent.trace_context import span_decorator

    @span_decorator("my-skill")
    async def my_func(x):
        ...
"""
from __future__ import annotations

import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from typing import Any, Awaitable, Callable, Iterator, List

# ---------------------------------------------------------------------------
# Context vars — per-coroutine isolation
# ---------------------------------------------------------------------------

_trace_id_var: ContextVar[str] = ContextVar("trace_id", default="")
_event_log_var: ContextVar[List[dict]] = ContextVar("event_log", default=[])


# ---------------------------------------------------------------------------
# Public API — trace_id
# ---------------------------------------------------------------------------


def get_trace_id() -> str:
    """Return the current trace_id.

    If none has been set, generates one automatically (lazy init).
    """
    tid = _trace_id_var.get()
    if not tid:
        tid = _generate_uuid()
        _trace_id_var.set(tid)
    return tid


def new_trace_id() -> str:
    """Generate a new UUID v4 trace_id and set it on the current context.

    Also resets the event log for the new trace.

    Returns:
        The new trace_id string.
    """
    tid = _generate_uuid()
    _trace_id_var.set(tid)
    _event_log_var.set([])
    return tid


# ---------------------------------------------------------------------------
# Public API — event log
# ---------------------------------------------------------------------------


def get_event_log() -> List[dict]:
    """Return the structured event log for the current context.

    Each entry is a dict with keys:
    ``trace_id``, ``span_name``, ``start_ms``, ``end_ms``, ``duration_ms``,
    ``success``, and optionally ``error``.
    """
    return _event_log_var.get()


def clear_event_log() -> None:
    """Empty the event log for the current context."""
    _event_log_var.set([])


# ---------------------------------------------------------------------------
# Span as context manager
# ---------------------------------------------------------------------------


@contextmanager
def span(name: str) -> Iterator[None]:
    """Context manager that records a timing span in the event log.

    Usage::

        with span("classify"):
            result = classifier.classify(message)

    Args:
        name: Span name — typically the stage/skill name.
    """
    trace_id = get_trace_id()
    start_ns = time.perf_counter_ns()
    success = True
    try:
        yield
    except BaseException:
        success = False
        raise
    finally:
        duration_ns = time.perf_counter_ns() - start_ns
        duration_ms = duration_ns / 1_000_000
        entry = {
            "trace_id": trace_id,
            "span_name": name,
            "duration_ms": round(duration_ms, 3),
            "success": success,
        }
        log = _event_log_var.get()
        log.append(entry)
        _event_log_var.set(log)


# ---------------------------------------------------------------------------
# Span as decorator (sync and async)
# ---------------------------------------------------------------------------


def span_decorator(name: str) -> Callable:
    """Decorator that wraps a function with span timing.

    Can decorate both sync and async functions.

    Usage::

        @span_decorator("classify")
        def classify(msg: str) -> str: ...

        @span_decorator("classify")
        async def classify(msg: str) -> str: ...

    Args:
        name: Span name to record in the event log.

    Returns:
        A decorator that applies to sync or async callables.
    """

    def decorator(fn: Callable) -> Callable:
        if _is_async(fn):

            @wraps(fn)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                with span(name):
                    return await fn(*args, **kwargs)

            return async_wrapper
        else:

            @wraps(fn)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                with span(name):
                    return fn(*args, **kwargs)

            return sync_wrapper

    return decorator


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _generate_uuid() -> str:
    """Generate a UUID v4 string."""
    return str(uuid.uuid4())


def _is_async(fn: Callable) -> bool:
    """Check whether a callable is an async function."""
    import asyncio
    return asyncio.iscoroutinefunction(fn)
