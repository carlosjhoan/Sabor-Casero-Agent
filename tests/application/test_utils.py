"""
Application logic tests for utility functions (src/utils/utils.py).

Tests pure logic — no LLM, no I/O (except controlled tmp_path for template files).
"""
import pytest
import os
from datetime import datetime
from src.utils.utils import build_prompt, safe_json_string, DateTimeEncoder, print_section


class TestBuildPrompt:
    """Tests for build_prompt()."""

    def test_build_prompt_basic(self, tmp_path):
        """Create a temp template file, inject variables, verify output."""
        template = tmp_path / "template.txt"
        template.write_text("Hola {name}, tu pedido de {dish} está listo.", encoding="utf-8")
        result = build_prompt(str(template), name="Juan", dish="Tacos al Pastor")
        assert result == "Hola Juan, tu pedido de Tacos al Pastor está listo."

    def test_build_prompt_missing_file(self):
        """Non-existent path → FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            build_prompt("/no/such/template.txt")

    def test_build_prompt_missing_variable(self, tmp_path):
        """Template requires var not provided → KeyError."""
        template = tmp_path / "template.txt"
        template.write_text("{name} {dish}", encoding="utf-8")
        with pytest.raises(KeyError):
            build_prompt(str(template), name="Juan")


class TestSafeJsonString:
    """Tests for safe_json_string()."""

    def test_safe_json_string_empty(self):
        """Empty string → empty string."""
        assert safe_json_string("") == ""

    def test_safe_json_string_normal(self):
        """Normal text → cleaned (no markdown stripping needed)."""
        result = safe_json_string("Hola, esto es una prueba")
        assert result == "Hola, esto es una prueba"

    def test_safe_json_string_with_markdown(self):
        """Strips #, ##, ---, **, __ markdown markers."""
        text = "# Título\n## Subtítulo\n**negrita** __cursiva__\n---separador"
        result = safe_json_string(text)
        assert "#" not in result
        assert "---" not in result
        assert "**" not in result
        assert "__" not in result
        # Text content should still be present
        assert "Título" in result
        assert "Subtítulo" in result
        assert "negrita" in result
        assert "cursiva" in result
        assert "separador" in result

    def test_safe_json_string_none(self):
        """None → empty string."""
        assert safe_json_string(None) == ""


class TestDateTimeEncoder:
    """Tests for DateTimeEncoder."""

    def test_datetime_encoder(self):
        """datetime → isoformat string."""
        import json
        dt = datetime(2026, 5, 19, 13, 30, 0)
        encoder = DateTimeEncoder()
        result = encoder.default(dt)
        assert result == "2026-05-19T13:30:00"


class TestPrintSection:
    """Tests for print_section()."""

    def test_print_section(self, capsys):
        """Smoke test — verify no crash and prints expected output."""
        print_section(head="Test Header", msg="Test Message", symbol="*")
        captured = capsys.readouterr()
        assert "Test Header" in captured.out
        assert "Test Message" in captured.out
