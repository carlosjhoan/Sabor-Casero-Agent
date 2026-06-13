"""
Tests for TraceContext (Task 3.2).

Covers trace_id generation, contextvars propagation, span decorator (timing +
structured event log), and get_trace_id / new_trace_id.
"""
import time
import pytest


class TestTraceId:
    """Verify trace_id generation and access."""

    def test_get_trace_id_returns_string(self):
        """get_trace_id() returns a string."""
        from src.engine.trace_context import get_trace_id
        tid = get_trace_id()
        assert isinstance(tid, str)
        assert len(tid) > 0

    def test_get_trace_id_stable_in_same_context(self):
        """get_trace_id() returns the same ID within the same trace context."""
        from src.engine.trace_context import get_trace_id, new_trace_id
        new_trace_id()
        first = get_trace_id()
        second = get_trace_id()
        assert first == second

    def test_new_trace_id_generates_different_id(self):
        """new_trace_id() resets to a new value."""
        from src.engine.trace_context import get_trace_id, new_trace_id
        new_trace_id()
        first = get_trace_id()
        new_trace_id()
        second = get_trace_id()
        assert first != second

    def test_new_trace_id_returns_uuid_string(self):
        """new_trace_id() returns the new UUID as a string."""
        from src.engine.trace_context import new_trace_id
        tid = new_trace_id()
        assert isinstance(tid, str)
        assert len(tid) == 36  # UUID v4 format
        assert tid.count("-") == 4

    def test_trace_id_propagated_via_contextvars(self):
        """trace_id set in one context is isolated from another."""
        from src.engine.trace_context import new_trace_id, get_trace_id
        import asyncio

        new_trace_id()
        main_tid = get_trace_id()

        async def in_separate_context():
            new_trace_id()
            return get_trace_id()

        child_tid = asyncio.run(in_separate_context())
        assert child_tid != main_tid
        assert get_trace_id() == main_tid  # main context unchanged


class TestSpanContextManager:
    """Verify the ``span()`` context manager."""

    def test_span_context_manager_records_event(self):
        """A span context manager adds a structured event to the log."""
        from src.engine.trace_context import span, get_event_log, new_trace_id, get_trace_id

        new_trace_id()
        tid = get_trace_id()
        with span("test-span"):
            pass

        log = get_event_log()
        assert len(log) == 1
        entry = log[0]
        assert entry["trace_id"] == tid
        assert entry["span_name"] == "test-span"
        assert entry["success"] is True
        assert "duration_ms" in entry
        assert isinstance(entry["duration_ms"], (int, float))
        assert entry["duration_ms"] >= 0

    def test_span_timing_is_accurate(self):
        """Span duration_ms approximates real wall-clock time."""
        from src.engine.trace_context import span, get_event_log, new_trace_id

        new_trace_id()
        with span("timing-test"):
            time.sleep(0.05)  # 50ms

        log = get_event_log()
        assert len(log) == 1
        # Allow generous tolerance on CI
        assert log[0]["duration_ms"] >= 30
        assert log[0]["success"] is True

    def test_span_records_failure(self):
        """Span captures failure when the body raises."""
        from src.engine.trace_context import span, get_event_log, new_trace_id

        new_trace_id()
        try:
            with span("failing-span"):
                raise ValueError("boom")
        except ValueError:
            pass

        log = get_event_log()
        assert len(log) == 1
        assert log[0]["span_name"] == "failing-span"
        assert log[0]["success"] is False
        assert "duration_ms" in log[0]

    def test_span_nesting(self):
        """Nested spans produce ordered event log entries."""
        from src.engine.trace_context import span, get_event_log, new_trace_id

        new_trace_id()
        with span("outer"):
            with span("inner"):
                pass

        log = get_event_log()
        assert len(log) == 2
        # Inner finishes first, so log[0] is inner, log[1] is outer
        assert log[0]["span_name"] == "inner"
        assert log[1]["span_name"] == "outer"
        assert log[0]["trace_id"] == log[1]["trace_id"]

    def test_multiple_traces_isolated_events(self):
        """Events from different traces are isolated."""
        from src.engine.trace_context import span, get_event_log, new_trace_id, clear_event_log

        new_trace_id()
        with span("trace-a-span"):
            pass

        trace_a_events = get_event_log()
        assert len(trace_a_events) == 1
        assert trace_a_events[0]["span_name"] == "trace-a-span"

        clear_event_log()
        new_trace_id()
        with span("trace-b-span"):
            pass

        trace_b_events = get_event_log()
        assert len(trace_b_events) == 1
        assert trace_b_events[0]["span_name"] == "trace-b-span"

    def test_clear_event_log(self):
        """clear_event_log() empties the event log."""
        from src.engine.trace_context import span, get_event_log, clear_event_log, new_trace_id

        new_trace_id()
        with span("ephemeral"):
            pass
        assert len(get_event_log()) == 1

        clear_event_log()
        assert len(get_event_log()) == 0


class TestSpanDecorator:
    """Verify the ``@span`` decorator."""

    def test_span_decorator_records_event(self):
        """@span decorator records a structured event for the function call."""
        from src.engine.trace_context import span_decorator, get_event_log, new_trace_id

        new_trace_id()

        @span_decorator("decorated-fn")
        def my_func(x):
            return x * 2

        result = my_func(21)
        assert result == 42

        log = get_event_log()
        assert len(log) == 1
        assert log[0]["span_name"] == "decorated-fn"
        assert log[0]["success"] is True

    def test_span_decorator_records_failure(self):
        """@span decorator captures failure when the function raises."""
        from src.engine.trace_context import span_decorator, get_event_log, new_trace_id

        new_trace_id()

        @span_decorator("failing-fn")
        def will_fail():
            raise RuntimeError("fail")

        with pytest.raises(RuntimeError):
            will_fail()

        log = get_event_log()
        assert len(log) == 1
        assert log[0]["span_name"] == "failing-fn"
        assert log[0]["success"] is False

    def test_span_decorator_async(self):
        """@span decorator works on async functions."""
        from src.engine.trace_context import span_decorator, get_event_log, new_trace_id

        new_trace_id()

        @span_decorator("async-fn")
        async def my_async(x):
            return x + 1

        import asyncio
        result = asyncio.run(my_async(5))
        assert result == 6

        log = get_event_log()
        assert len(log) == 1
        assert log[0]["span_name"] == "async-fn"
        assert log[0]["success"] is True
