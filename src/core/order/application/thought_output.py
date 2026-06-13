"""
ThoughtOutput — Modelo estructurado de salida del ThoughtGenerator.

Contiene el razonamiento en texto libre (reasoning) más una declaración
explícita de ambigüedad (ambiguity) que el AmbiguityResolver utiliza
para decidir si bloquear o no la ejecución de acciones.

Este modelo se usa con response_format="json_object" + output_format
en el LLMClient para garantizar que la salida sea JSON válido sin
necesidad de post-procesamiento con expresiones regulares.
"""

from pydantic import BaseModel
from typing import Optional


class AmbiguityDeclaration(BaseModel):
    """
    Declaración estructurada de ambigüedad detectada por el ThoughtGenerator.

    El LLM declara aquí, en el momento de razonar, si la solicitud del
    usuario es ambigua con respecto a las acciones que deben ejecutarse.
    """

    has_ambiguity: bool
    """Indica si hay ambigüedad REAL que impide ejecutar acciones."""

    ambiguous_topics: list[str] = []
    """Lista de tópicos específicos que son ambiguos (ej: ["proteína", "tamaño"])."""

    clarifying_question: Optional[str] = None
    """Pregunta de clarificación sugerida para el usuario, si aplica."""


class ThoughtOutput(BaseModel):
    """
    Salida completa del ThoughtGenerator.

    Reemplaza la salida de texto libre con un objeto estructurado que
    contiene tanto el razonamiento (para el ActionPlanner) como la
    declaración de ambigüedad (para el AmbiguityResolver).
    """

    reasoning: str
    """Razonamiento completo del LLM en español (texto libre, 3-5 oraciones)."""

    ambiguity: AmbiguityDeclaration
    """Declaración de ambigüedad detectada durante el razonamiento."""
