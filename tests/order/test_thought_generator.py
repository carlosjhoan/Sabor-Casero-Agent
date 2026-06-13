"""
Tests para ThoughtGenerator — v3.0 (texto libre + línea de ambigüedad explícita).

Verifica que generate_thought():
1. Use una sola llamada a LLM con salida de TEXTO LIBRE (sin JSON, sin structured output)
2. Parsee la línea explícita "Ambigüedad: Sí/No" del texto generado
3. Use fallback resiliente (success=True) si el LLM devuelve vacío o lanza excepción
"""

import pytest
from unittest.mock import AsyncMock, patch
from src.core.order.application.thought_generator import ThoughtGenerator
from src.core.order.application.thought_output import ThoughtOutput, AmbiguityDeclaration
from src.core.classifier.intent import Detail, QueryTopic, QueryType
from src.infrastructure.llm_client import LLMClient
from tests.helpers.mock_repositories import InMemoryOrderRepository, InMemorySessionRepository


# ── Helpers ───────────────────────────────────────────────────────


def _make_llm_response(reasoning: str, ambiguity_line: str) -> str:
    """Construye un texto simulado de respuesta del LLM con línea de ambigüedad."""
    return f"{reasoning}\n\n{ambiguity_line}"


# ── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def ordering_segments():
    """Segmentos de ordening de prueba."""
    return [
        Detail(
            segment="quiero tacos al pastor",
            focus="quiero tacos al pastor",
            topic=QueryTopic.MENU,
            query_type=QueryType.ORDERING,
            info_extracted="Tacos al pastor: $45.00",
        ),
    ]


@pytest.fixture
def session_repo():
    repo = InMemorySessionRepository()
    repo.create_session(customer_id="test-customer")
    return repo


@pytest.fixture
def order_repo():
    return InMemoryOrderRepository()


@pytest.fixture
def generator(mock_llm_client, session_repo, order_repo):
    return ThoughtGenerator(
        session_repository=session_repo,
        order_repository=order_repo,
        llm_client=mock_llm_client,
    )


# ── Tests: generate_thought (integración con mock LLM) ────────────


class TestThoughtGeneratorV3:
    """Tests para el flujo v3.0: texto libre + línea de ambigüedad."""

    async def test_single_call_returns_correct_keys(
        self, generator, ordering_segments, mock_llm_client
    ):
        """
        LLM devuelve texto libre con ambigüedad: No →
        result tiene las claves correctas.
        """
        mock_llm_client.chat_completion.return_value = _make_llm_response(
            "El usuario quiere tacos al pastor. Acción clara y directa.",
            "Ambigüedad: No. No hay ambigüedad detectada.",
        )

        result = await generator.generate_thought(
            ordering_segments=ordering_segments,
            session_id="ses-001",
        )

        assert result["success"] is True
        assert "thought" in result
        assert "ambiguity" in result
        assert "context" in result
        assert "processor_input" in result
        assert "error" not in result or result["error"] is None

    async def test_thought_is_clean_text(
        self, generator, ordering_segments, mock_llm_client
    ):
        """
        Verificar que result['thought'] sea texto limpio,
        no JSON ni representación de objeto.
        """
        mock_llm_client.chat_completion.return_value = _make_llm_response(
            "El usuario quiere tacos al pastor. Acción clara.",
            "Ambigüedad: No. Se puede proceder.",
        )

        result = await generator.generate_thought(
            ordering_segments=ordering_segments,
            session_id="ses-001",
        )

        assert isinstance(result["thought"], str)
        # Verificar que no sea JSON ni repr de objeto
        assert not result["thought"].startswith("{")
        assert not result["thought"].startswith("[")
        assert not result["thought"].startswith("reasoning=")
        # Verificar que sea texto legible
        assert "tacos" in result["thought"] or "usuario" in result["thought"]

    async def test_ambiguity_declaration_from_text(
        self, generator, ordering_segments, mock_llm_client
    ):
        """
        LLM devuelve texto con Ambigüedad: Sí →
        result['ambiguity'] refleja la ambigüedad correctamente.
        """
        mock_llm_client.chat_completion.return_value = _make_llm_response(
            "El usuario quiere tacos pero no especifica el tipo de carne.",
            "Ambigüedad: Sí — El tipo de carne no está especificado.",
        )

        result = await generator.generate_thought(
            ordering_segments=ordering_segments,
            session_id="ses-001",
        )

        assert isinstance(result["ambiguity"], AmbiguityDeclaration)
        assert result["ambiguity"].has_ambiguity is True
        assert "tipo de carne" in result["ambiguity"].ambiguous_topics[0]

    async def test_non_empty_string_response_succeeds(
        self, generator, ordering_segments, mock_llm_client
    ):
        """
        Cualquier string no vacío del LLM es válido en v3.0.
        Texto sin Ambigüedad: → safe default (has_ambiguity=False).
        """
        mock_llm_client.chat_completion.return_value = (
            "Esto es texto libre sin línea de ambigüedad explícita."
        )

        result = await generator.generate_thought(
            ordering_segments=ordering_segments,
            session_id="ses-001",
        )

        assert result["success"] is True
        assert isinstance(result["thought"], str)
        assert isinstance(result["ambiguity"], AmbiguityDeclaration)
        assert result["ambiguity"].has_ambiguity is False

    async def test_empty_llm_response_fallback(
        self, generator, ordering_segments, mock_llm_client
    ):
        """
        LLM devuelve None (content vacío desde _parse_response)
        → fallback resiliente: success=True con thought genérico.
        El pipeline CONTINÚA en vez de morir.
        """
        mock_llm_client.chat_completion.return_value = None

        result = await generator.generate_thought(
            ordering_segments=ordering_segments,
            session_id="ses-001",
        )

        assert result["success"] is True
        assert isinstance(result["thought"], str)
        assert "no pudo generar razonamiento" in result["thought"]
        assert isinstance(result["ambiguity"], AmbiguityDeclaration)
        assert result["ambiguity"].has_ambiguity is False
        assert "error" in result

    async def test_error_handling_fallback(
        self, generator, ordering_segments, mock_llm_client
    ):
        """
        LLM lanza excepción → fallback resiliente.
        success=True en vez de False para que el pipeline CONTINÚE.
        """
        mock_llm_client.chat_completion.side_effect = Exception("API connection error")

        result = await generator.generate_thought(
            ordering_segments=ordering_segments,
            session_id="ses-001",
        )

        assert result["success"] is True
        assert isinstance(result["thought"], str)
        assert "no pudo generar razonamiento" in result["thought"]
        assert isinstance(result["ambiguity"], AmbiguityDeclaration)
        assert result["ambiguity"].has_ambiguity is False
        assert "error" in result
        assert "API connection error" in result["error"]


# ── Tests: _parse_ambiguity_line (unidad) ─────────────────────────


class TestParseAmbiguityLine:
    """Tests unitarios para _parse_ambiguity_line()."""

    def test_si_with_description(self, generator):
        """Ambigüedad: Sí con descripción → has_ambiguity=True, tópico capturado."""
        text = (
            "El usuario pide tacos pero no dice de qué carne.\n\n"
            "Ambigüedad: Sí — El tipo de carne no está especificado."
        )
        result = generator._parse_ambiguity_line(text)
        assert isinstance(result, AmbiguityDeclaration)
        assert result.has_ambiguity is True
        assert "tipo de carne" in result.ambiguous_topics[0]
        assert "tipo de carne" in result.clarifying_question

    def test_si_without_description(self, generator):
        """Ambigüedad: Sí sin descripción → has_ambiguity=True, listas vacías."""
        text = "Texto de prueba.\n\nAmbigüedad: Sí"
        result = generator._parse_ambiguity_line(text)
        assert result.has_ambiguity is True
        assert result.ambiguous_topics == []
        assert result.clarifying_question is None

    def test_si_dash_variants(self, generator):
        """Ambigüedad: Sí con distintos separadores → todos parsean."""
        cases = [
            ("Ambigüedad: Sí — algo", "algo"),
            ("Ambigüedad: Sí - algo", "algo"),
            ("Ambigüedad: Sí: algo", "algo"),
            ("Ambigüedad: Sí. algo", "algo"),
            ("Ambigüedad: Sí–algo", "algo"),
        ]
        for text, expected in cases:
            result = generator._parse_ambiguity_line(text)
            assert result.has_ambiguity is True, f"Falló para: {text}"

    def test_no_with_description(self, generator):
        """Ambigüedad: No con descripción → has_ambiguity=False."""
        text = (
            "El usuario quiere tacos al pastor. Todo claro.\n\n"
            "Ambigüedad: No. Se puede proceder con la planificación."
        )
        result = generator._parse_ambiguity_line(text)
        assert result.has_ambiguity is False
        assert result.ambiguous_topics == []
        assert result.clarifying_question is None

    def test_no_without_description(self, generator):
        """Ambigüedad: No sin descripción → has_ambiguity=False."""
        text = "Texto de prueba.\n\nAmbigüedad: No"
        result = generator._parse_ambiguity_line(text)
        assert result.has_ambiguity is False
        assert result.ambiguous_topics == []
        assert result.clarifying_question is None

    def test_missing_line(self, generator):
        """Sin línea de ambigüedad → safe default has_ambiguity=False."""
        text = "El usuario quiere tacos al pastor. No hay ambigüedad."
        result = generator._parse_ambiguity_line(text)
        assert result.has_ambiguity is False
        assert result.ambiguous_topics == []
        assert result.clarifying_question is None

    def test_empty_text(self, generator):
        """Texto vacío → safe default has_ambiguity=False."""
        result = generator._parse_ambiguity_line("")
        assert result.has_ambiguity is False

    def test_case_insensitive(self, generator):
        """AMBIGÜEDAD: mayúscula/minúscula mixta → funciona."""
        text = "Texto.\n\nAMBIGÜEDAD: Sí — prueba."
        result = generator._parse_ambiguity_line(text)
        assert result.has_ambiguity is True

    def test_ambiguity_line_in_middle(self, generator):
        """Línea de ambigüedad en medio del texto (no al final) → igual se parsea."""
        text = (
            "Razonamiento inicial.\n"
            "Ambigüedad: No. Sigue siendo seguro.\n"
            "Más razonamiento después."
        )
        result = generator._parse_ambiguity_line(text)
        assert result.has_ambiguity is False

    def test_multiple_ambiguity_lines(self, generator):
        """Múltiples líneas de ambigüedad → usa la primera que matchea."""
        text = (
            "Primera parte.\n"
            "Ambigüedad: Sí — problema 1.\n"
            "Ambigüedad: No. Esto se ignora.\n"
        )
        result = generator._parse_ambiguity_line(text)
        assert result.has_ambiguity is True
        assert "problema 1" in result.ambiguous_topics[0]


# ── Tests: infraestructura (init, context, input) ────────────────


class TestThoughtGeneratorInfrastructure:
    """Tests de infraestructura: init, carga de contexto, formateo de input."""

    def test_init_with_default_client(self):
        """
        Task 5.6: ThoughtGenerator crea cliente default cuando
        llm_client=None.
        """
        with patch(
            "src.core.order.application.thought_generator.get_llm_client_for_stage"
        ) as mock_factory:
            mock_factory.return_value = AsyncMock(spec=LLMClient)

            generator = ThoughtGenerator(
                session_repository=InMemorySessionRepository(),
                order_repository=InMemoryOrderRepository(),
                llm_client=None,
            )

            mock_factory.assert_called_once_with("thought_generator")
            assert generator.llm_client is not None

    async def test_load_order_context(
        self, generator, session_repo
    ):
        """
        Task 5.7: verificar que _load_order_context funciona con
        sesión existente pero sin orden.
        """
        result = await generator._load_order_context("ses-001")

        assert "session" in result
        assert result["session"] is not None
        assert result["order_id"] is None
        assert "El cliente no ha realizado pedido" in result["summary"]

    def test_prepare_processor_input(
        self, generator, ordering_segments
    ):
        """
        Task 5.8: verificar formato de salida de _prepare_processor_input.
        """
        result = generator._prepare_processor_input(ordering_segments)

        assert "Segmento 1" in result
        assert "User says: quiero tacos al pastor" in result
        assert "Focus:" in result
        assert "Info:" in result
