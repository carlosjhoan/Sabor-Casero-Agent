"""
Tests for empty response guard (Task 1.4, FR-P1-03).

When response builder returns "", the pipeline MUST replace it with
FALLBACK_ERROR and log the event.

Note: In the skill-based architecture, the empty-response guard lives
in the ``response-build`` skill (``skills/response_build/__init__.py``).
Its ``FALLBACK_ERROR`` is the canonical empty-response replacement.
"""
import pytest


# The canonical fallback used by the response-build skill
_SKILL_FALLBACK = (
    "Lo siento, no pude generar una respuesta. Por favor intenta de nuevo."
)


class TestEmptyResponseGuard:
    """Verify empty responses are caught before returning to user."""

    @pytest.mark.asyncio
    async def test_empty_response_is_replaced_with_fallback(self, assistant):
        """When response_builder returns '', pipeline returns FALLBACK_ERROR."""
        assistant.response_builder.build_hybrid.return_value = ""
        result = await assistant.process_message("user1", "Hola", "test-session")

        assert result["response"] == _SKILL_FALLBACK
        assert result["classification"] is not None

    @pytest.mark.asyncio
    async def test_normal_response_passes_through(self, assistant):
        """A normal non-empty response passes through unchanged."""
        assistant.response_builder.build_hybrid.return_value = (
            "¡Claro! Aquí tienes la información."
        )
        result = await assistant.process_message("user1", "Hola", "test-session")
        assert result["response"] == "¡Claro! Aquí tienes la información."
        assert "pipeline_error" not in result

    @pytest.mark.asyncio
    async def test_whitespace_only_is_replaced(self, assistant):
        """Whitespace-only responses are treated as empty."""
        assistant.response_builder.build_hybrid.return_value = "   \n  "
        result = await assistant.process_message("user1", "Hola", "test-session")
        assert result["response"] == _SKILL_FALLBACK
