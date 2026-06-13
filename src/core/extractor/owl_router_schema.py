"""
Esquema Pydantic para el ruteo de consultas del menú vía LLM.

Define MenuQuery, el modelo estructurado que el LLM debe generar
para clasificar la intención del usuario y extraer parámetros.
"""
from typing import Literal, Optional

from pydantic import BaseModel, Field


class MenuQuery(BaseModel):
    """
    Consulta estructurada del menú generada por el LLM router.

    Clasifica la intención del usuario en uno de 5 tipos y extrae
    el nombre de sección e ítem cuando corresponde.

    Attributes:
        intent: Tipo de consulta clasificada.
        section: Nombre de la sección (para section_items).
        item: Nombre del ítem (para item_price / item_options).
        confidence: Nivel de confianza de la clasificación (0.0–1.0).
    """

    intent: Literal[
        "full_menu", "section_items", "item_price", "item_options", "unknown"
    ]
    section: Optional[str] = None
    item: Optional[str] = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
