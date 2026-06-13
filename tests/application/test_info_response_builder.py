"""
Application logic tests for InfoResponseBuilder (info_response_builder.py).

Tests pure logic — no LLM, no I/O, no async.
"""
import pytest
from src.core.response.info_response_builder import InfoResponseBuilder
from src.core.classifier.intent import Detail, QueryType, QueryTopic


class TestInfoResponseBuilderProcess:
    """Tests for InfoResponseBuilder.process()."""

    def test_process_empty_segments(self):
        """Empty list → empty string."""
        builder = InfoResponseBuilder()
        result = builder.process([])
        assert result == ""

    def test_process_greeting_only(self):
        """GREETING topic → empty string (filtered by NO_RAG_TOPICS)."""
        builder = InfoResponseBuilder()
        detail = Detail(
            segment="hola",
            query_type=QueryType.CONSULTING,
            topic=QueryTopic.GREETING,
            focus="saludo cordial al cliente",
        )
        result = builder.process([detail])
        assert result == ""

    def test_process_with_extracted_info(self):
        """Segment with info_extracted → returns the info."""
        builder = InfoResponseBuilder()
        detail = Detail(
            segment="qué tienen de menú",
            query_type=QueryType.CONSULTING,
            topic=QueryTopic.MENU,
            focus="qué tienen de menú disponible",
            info_extracted="Tenemos Tacos, Burritos y Quesadillas",
        )
        result = builder.process([detail])
        assert result == "Tenemos Tacos, Burritos y Quesadillas"

    def test_process_no_info_extracted(self):
        """Segment without info_extracted → fallback response."""
        builder = InfoResponseBuilder()
        detail = Detail(
            segment="qué tienen de menú",
            query_type=QueryType.CONSULTING,
            topic=QueryTopic.MENU,
            focus="qué tienen de menú disponible",
            # info_extracted is empty by default
        )
        result = builder.process([detail])
        assert "[INFO_NO_DISPONIBLE: topic=menu, focus=qué tienen de menú disponible]" in result

    def test_process_multiple_segments(self):
        """Multiple segments → joined with ' | '."""
        builder = InfoResponseBuilder()
        detail1 = Detail(
            segment="qué tienen de menú",
            query_type=QueryType.CONSULTING,
            topic=QueryTopic.MENU,
            focus="qué tienen de menú disponible",
            info_extracted="Tenemos Tacos, Burritos y Quesadillas",
        )
        detail2 = Detail(
            segment="cómo puedo pagar",
            query_type=QueryType.CONSULTING,
            topic=QueryTopic.PAYMENT,
            focus="cómo puedo pagar la cuenta",
            info_extracted="Aceptamos efectivo y tarjeta",
        )
        result = builder.process([detail1, detail2])
        assert "Tenemos Tacos, Burritos y Quesadillas" in result
        assert "Aceptamos efectivo y tarjeta" in result
        assert " | " in result


class TestInfoResponseBuilderHelpers:
    """Tests for InfoResponseBuilder helper methods."""

    def test_is_consulting_segment(self):
        """CONSULTING query_type → True."""
        builder = InfoResponseBuilder()
        detail = Detail(
            segment="dame información",
            query_type=QueryType.CONSULTING,
            topic=QueryTopic.MENU,
            focus="dame información del menú completo",
        )
        assert builder.is_consulting_segment(detail) is True

    def test_is_consulting_segment_false(self):
        """ORDERING query_type → False."""
        builder = InfoResponseBuilder()
        detail = Detail(
            segment="quiero ordenar",
            query_type=QueryType.ORDERING,
            topic=QueryTopic.MENU,
            focus="quiero ordenar tacos al pastor",
        )
        assert builder.is_consulting_segment(detail) is False

    def test_filter_consulting_segments(self):
        """Filters only CONSULTING segments."""
        builder = InfoResponseBuilder()
        details = [
            Detail(
                segment="dame información",
                query_type=QueryType.CONSULTING,
                topic=QueryTopic.MENU,
                focus="dame información del menú completo",
            ),
            Detail(
                segment="quiero ordenar",
                query_type=QueryType.ORDERING,
                topic=QueryTopic.MENU,
                focus="quiero ordenar tacos al pastor",
            ),
        ]
        result = builder.filter_consulting_segments(details)
        assert len(result) == 1
        assert result[0].query_type == QueryType.CONSULTING

    def test_build_fallback_response(self):
        """Verifies fallback format."""
        builder = InfoResponseBuilder()
        result = builder._build_fallback_response(QueryTopic.MENU, "precio del lomo")
        assert result == "[INFO_NO_DISPONIBLE: topic=menu, focus=precio del lomo]"
