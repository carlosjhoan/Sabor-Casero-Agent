"""
Domain model tests for input_guard.py — GuardResult dataclass, fast heuristic checks, truncation.
"""
from src.core.classifier.input_guard import (
    GuardResult,
    check_message_quality_fast,
    truncate_message,
)


class TestGuardResult:
    """Tests for GuardResult dataclass."""

    def test_guard_result_creation(self):
        """GuardResult dataclass fields."""
        result = GuardResult(is_valid=True)
        assert result.is_valid is True
        assert result.reason is None
        assert result.fallback_response is None

        result2 = GuardResult(
            is_valid=False,
            reason="mensaje_vacio",
            fallback_response="Por favor escribe algo",
        )
        assert result2.is_valid is False
        assert result2.reason == "mensaje_vacio"
        assert result2.fallback_response == "Por favor escribe algo"


class TestCheckMessageQualityFast:
    """Tests for check_message_quality_fast."""

    def test_check_message_quality_fast_empty(self):
        """Empty string rejected."""
        result = check_message_quality_fast("")
        assert result.is_valid is False
        assert result.reason == "mensaje_vacio"

    def test_check_message_quality_fast_too_short(self):
        """Single char rejected."""
        result = check_message_quality_fast("a")
        assert result.is_valid is False
        assert result.reason == "mensaje_muy_corto"

    def test_check_message_quality_fast_repeated_chars(self):
        """6+ repeated chars rejected."""
        result = check_message_quality_fast("aaaaaa")
        assert result.is_valid is False
        assert result.reason == "caracteres_repetidos"

        # 5 repeated chars should be allowed
        result2 = check_message_quality_fast("aaaaa")
        assert result2.is_valid is True

    def test_check_message_quality_fast_valid(self):
        """Normal message accepted."""
        result = check_message_quality_fast("Hola, quiero ordenar tacos")
        assert result.is_valid is True
        assert result.reason is None


class TestTruncateMessage:
    """Tests for truncate_message."""

    def test_truncate_message_short(self):
        """Message under limit unchanged."""
        msg = "Hola, quiero ordenar tacos"
        result = truncate_message(msg, max_length=800)
        assert result == msg

    def test_truncate_message_long(self):
        """Message over limit truncated at word boundary."""
        # Create a message that exceeds max_length
        base = "palabra " * 200  # 200 words ~= 1600 chars
        result = truncate_message(base, max_length=100)
        assert len(result) <= 100 + 3  # +3 for "..."
        assert result.endswith("...")
        # The truncated part should cut at a word boundary (no partial word before ...)
        truncated_text = result[:-3]
        assert truncated_text == truncated_text.rstrip()  # no trailing space

    def test_truncate_message_exact(self):
        """Message exactly at limit unchanged."""
        msg = "a" * 100
        result = truncate_message(msg, max_length=100)
        assert result == msg
        assert len(result) == 100
