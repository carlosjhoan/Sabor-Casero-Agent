"""
Tests para ThoughtOutput y AmbiguityDeclaration BaseModels.

Verifica que la serialización/deserialización JSON funcione
correctamente, ya que estos modelos se usan con
response_format="json_object" en el LLM.
"""

import json
from src.core.order.application.thought_output import (
    ThoughtOutput,
    AmbiguityDeclaration,
)


class TestAmbiguityDeclaration:
    def test_default_values(self):
        """has_ambiguity=False por defecto genera valores vacíos."""
        decl = AmbiguityDeclaration(has_ambiguity=False)
        assert decl.has_ambiguity is False
        assert decl.ambiguous_topics == []
        assert decl.clarifying_question is None

    def test_ambiguous_with_topics(self):
        """Declaración ambigua con tópicos y pregunta."""
        decl = AmbiguityDeclaration(
            has_ambiguity=True,
            ambiguous_topics=["tipo de pechuga"],
            clarifying_question="¿Pechuga a la plancha o gratinada?",
        )
        assert decl.has_ambiguity is True
        assert "tipo de pechuga" in decl.ambiguous_topics
        assert decl.clarifying_question is not None

    def test_serialize_to_json(self):
        """Serialización JSON funciona correctamente."""
        decl = AmbiguityDeclaration(
            has_ambiguity=True,
            ambiguous_topics=["tamaño"],
        )
        data = decl.model_dump()
        assert data["has_ambiguity"] is True
        assert data["ambiguous_topics"] == ["tamaño"]
        assert data["clarifying_question"] is None

    def test_deserialize_from_json(self):
        """Deserialización desde JSON funciona."""
        json_str = json.dumps({
            "has_ambiguity": True,
            "ambiguous_topics": ["proteína", "tamaño"],
            "clarifying_question": "¿Cuál prefieres?",
        })
        decl = AmbiguityDeclaration.model_validate_json(json_str)
        assert decl.has_ambiguity is True
        assert len(decl.ambiguous_topics) == 2
        assert decl.clarifying_question == "¿Cuál prefieres?"


class TestThoughtOutput:
    def test_full_thought_output(self):
        """ThoughtOutput contiene reasoning + ambiguity."""
        ambiguity = AmbiguityDeclaration(
            has_ambiguity=True,
            ambiguous_topics=["tipo de pechuga"],
            clarifying_question="¿A la plancha o gratinada?",
        )
        output = ThoughtOutput(
            reasoning="El usuario quiere pechuga pero hay dos opciones.",
            ambiguity=ambiguity,
        )
        assert output.reasoning == "El usuario quiere pechuga pero hay dos opciones."
        assert output.ambiguity.has_ambiguity is True
        assert output.ambiguity.ambiguous_topics == ["tipo de pechuga"]

    def test_no_ambiguity_output(self):
        """ThoughtOutput sin ambigüedad."""
        output = ThoughtOutput(
            reasoning="El usuario pidió pechuga a la plancha mini. Válido.",
            ambiguity=AmbiguityDeclaration(has_ambiguity=False),
        )
        assert output.ambiguity.has_ambiguity is False
        assert output.ambiguity.ambiguous_topics == []

    def test_roundtrip_json(self):
        """model_dump() → JSON → model_validate_json() mantiene datos."""
        original = ThoughtOutput(
            reasoning="Razonamiento de prueba.",
            ambiguity=AmbiguityDeclaration(
                has_ambiguity=True,
                ambiguous_topics=["prueba"],
            ),
        )
        json_str = original.model_dump_json()
        restored = ThoughtOutput.model_validate_json(json_str)
        assert restored.reasoning == original.reasoning
        assert restored.ambiguity.has_ambiguity == original.ambiguity.has_ambiguity
        assert restored.ambiguity.ambiguous_topics == original.ambiguity.ambiguous_topics

    def test_model_json_schema(self):
        """Verificar que el schema JSON sea válido."""
        schema = ThoughtOutput.model_json_schema()
        assert "properties" in schema
        assert "reasoning" in schema["properties"]
        assert "ambiguity" in schema["properties"]
