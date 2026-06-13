"""
Tests para AmbiguityResolver — nueva versión basada en
declaración estructurada (AmbiguityDeclaration) en lugar de
keyword matching sobre texto libre.

Elimina los falsos positivos sistemáticos: el resolver
ahora confía en la declaración explícita del LLM.
"""

import pytest
from src.core.order.application.ambiguity_resolver import AmbiguityResolver
from src.core.order.application.thought_output import AmbiguityDeclaration


@pytest.fixture
def resolver():
    return AmbiguityResolver()


@pytest.fixture
def sample_actions():
    return [
        {"action": "CREATE_ITEM", "item_name": "Pechuga a la plancha", "size": "mini"},
    ]


class TestAmbiguityResolverStructured:
    """Tests para el nuevo flujo basado en AmbiguityDeclaration."""

    def test_no_declaration_returns_not_ambiguous(self, resolver, sample_actions):
        """Sin declaración estructurada → safe default: no ambigüedad."""
        result = resolver.resolve(
            thought="algún texto",
            actions=sample_actions,
            ambiguity_declaration=None,
        )
        assert result["is_ambiguous"] is False

    def test_explicit_not_ambiguous(self, resolver, sample_actions):
        """has_ambiguity=False explícito → no ambigüedad."""
        decl = AmbiguityDeclaration(has_ambiguity=False)
        result = resolver.resolve(
            thought="texto",
            actions=sample_actions,
            ambiguity_declaration=decl,
        )
        assert result["is_ambiguous"] is False

    def test_explicit_ambiguous_with_actions(self, resolver, sample_actions):
        """has_ambiguity=True + acciones problemáticas → ambigüedad detectada."""
        decl = AmbiguityDeclaration(
            has_ambiguity=True,
            ambiguous_topics=["tipo de pechuga"],
            clarifying_question="¿Pechuga a la plancha o gratinada?",
        )
        result = resolver.resolve(
            thought="texto",
            actions=sample_actions,
            ambiguity_declaration=decl,
        )
        assert result["is_ambiguous"] is True
        assert "tipo de pechuga" in result["signals"]
        assert result["ambiguity_context"] == "¿Pechuga a la plancha o gratinada?"
        assert result["confidence"] == 0.9

    def test_explicit_ambiguous_no_clarifying_question(self, resolver, sample_actions):
        """has_ambiguity=True sin clarifying_question → usa ambiguous_topics."""
        decl = AmbiguityDeclaration(
            has_ambiguity=True,
            ambiguous_topics=["tamaño"],
        )
        result = resolver.resolve(
            thought="texto",
            actions=sample_actions,
            ambiguity_declaration=decl,
        )
        assert result["is_ambiguous"] is True
        assert result["ambiguity_context"] == "tamaño"
        assert result["confidence"] == 0.7

    def test_ambiguous_but_no_ambiguous_actions(self, resolver):
        """has_ambiguity=True pero acciones NO problemáticas → no bloquea."""
        decl = AmbiguityDeclaration(
            has_ambiguity=True,
            ambiguous_topics=["dirección"],
        )
        metadata_actions = [
            {"action": "UPDATE_ORDER_META", "field": "address", "value": "Calle 123"}
        ]
        result = resolver.resolve(
            thought="texto",
            actions=metadata_actions,
            ambiguity_declaration=decl,
        )
        # Acciones de metadata no se bloquean aunque haya ambigüedad declarada
        assert result["is_ambiguous"] is False

    def test_empty_actions_with_ambiguity(self, resolver):
        """Sin acciones → nunca es ambiguo."""
        decl = AmbiguityDeclaration(
            has_ambiguity=True,
            ambiguous_topics=["proteína"],
        )
        result = resolver.resolve(
            thought="texto",
            actions=[],
            ambiguity_declaration=decl,
        )
        assert result["is_ambiguous"] is False


class TestAmbiguityResolverEdgeCases:
    """Casos borde específicos del escenario real."""

    def test_no_ambiguity_when_missing_info_is_normal(self, resolver):
        """
        Escenario real: usuario pide "Pechuga a la plancha mini".
        El thought dice "No se ha especificado principio, se debe preguntar".
        El LLM declara has_ambiguity=False porque la ACCIÓN no es ambigua
        (el principio es follow-up normal, no ambigüedad).
        """
        decl = AmbiguityDeclaration(
            has_ambiguity=False,
            ambiguous_topics=[],
            clarifying_question=None,
        )
        actions = [
            {
                "action": "CREATE_ITEM",
                "protein": "Pechuga a la plancha",
                "size": "mini",
            }
        ]
        result = resolver.resolve(
            thought="El usuario confirmó pechuga a la plancha mini. "
            "No se ha especificado principio, se debe preguntar.",
            actions=actions,
            ambiguity_declaration=decl,
        )
        assert result["is_ambiguous"] is False

    def test_ambiguity_when_protein_choice_is_unclear(self, resolver):
        """
        Escenario real: usuario pide "con pechuga".
        Hay pechuga a la plancha Y pechuga gratinada en el menú.
        La ACCIÓN de crear el item es ambigua.
        """
        decl = AmbiguityDeclaration(
            has_ambiguity=True,
            ambiguous_topics=["tipo de pechuga"],
            clarifying_question="¿Pechuga a la plancha o pechuga gratinada?",
        )
        actions = [
            {
                "action": "CREATE_ITEM",
                "protein": "Pechuga",
                "size": "corriente",
            }
        ]
        result = resolver.resolve(
            thought="El usuario pide pechuga pero hay dos opciones en el menú.",
            actions=actions,
            ambiguity_declaration=decl,
        )
        assert result["is_ambiguous"] is True
        assert "tipo de pechuga" in result["signals"]
