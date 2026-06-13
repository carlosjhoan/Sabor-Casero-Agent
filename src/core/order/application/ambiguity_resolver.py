"""
AmbiguityResolver — decide si las acciones planificadas deben ejecutarse
o si se necesita clarificación con el usuario.

AHORA utiliza la declaración estructurada de ambigüedad generada por el
ThoughtGenerator (AmbiguityDeclaration) en lugar de hacer keyword matching
sobre el texto libre del thought. Esto elimina los falsos positivos
sistemáticos causados por lenguaje de incertidumbre natural en el
razonamiento del LLM.

Flujo:
    ThoughtGenerator → genera ThoughtOutput (reasoning + ambiguity)
                     → AmbiguityResolver.resolve(ambiguity_declaration)
                         ├─ if has_ambiguity → return clarification context
                         └─ if not           → permitir ejecución de acciones
"""

from typing import Dict, List, Any, Optional

from src.core.order.application.thought_output import AmbiguityDeclaration


class AmbiguityResolver:
    """
    Resuelve ambigüedad basándose en la declaración estructurada del
    ThoughtGenerator, no en keywords sobre texto libre.

    Uso:
        resolver = AmbiguityResolver()
        result = resolver.resolve(
            ambiguity_declaration=thought_result.get("ambiguity"),
            actions=actions,
        )
        if result["is_ambiguous"]:
            # No ejecutar acciones, pasar ambiguity_context al response
    """

    # Tipos de acción que asumen una elección específica y deben bloquearse
    # cuando hay ambigüedad. Las acciones de consulta/metadata no se bloquean.
    AMBIGUOUS_ACTION_TYPES: List[str] = [
        "CREATE_ITEM",
        "UPDATE_ITEM",
        "DELETE_ITEM",
        "CREATE_ORDER",
    ]

    def resolve(
        self,
        thought: str,
        actions: List[Dict[str, Any]],
        context: Optional[Dict[str, Any]] = None,
        ambiguity_declaration: Optional[AmbiguityDeclaration] = None,
    ) -> Dict[str, Any]:
        """
        Punto de entrada principal.

        Args:
            thought: Razonamiento generado por ThoughtGenerator (texto libre).
                     Se mantiene por compatibilidad pero ya no se usa para
                     detección de ambigüedad.
            actions: Lista de acciones generadas por ActionPlanner.
            context: Contexto de orden (order_summary, etc.) — opcional.
            ambiguity_declaration: Declaración estructurada de ambigüedad
                                   desde el ThoughtGenerator.

        Returns:
            Dict con:
            - is_ambiguous: bool
            - ambiguity_context: str (qué está ambiguo, opciones disponibles)
            - signals: List[str] (tópicos ambiguos, desde la declaración)
            - confidence: float (0.0–1.0)
        """
        # Si no hay acciones, no hay nada que bloquear
        if not actions:
            return {"is_ambiguous": False}

        # PRIORIDAD 1: Usar declaración estructurada (si existe)
        if ambiguity_declaration is not None:
            if ambiguity_declaration.has_ambiguity:
                # Verificar que las acciones son del tipo que asume elección
                has_ambiguous_actions = any(
                    a.get("action") in self.AMBIGUOUS_ACTION_TYPES for a in actions
                )

                if not has_ambiguous_actions:
                    # Señal de ambigüedad pero acciones no problemáticas →
                    # el sistema ya manejó la ambigüedad correctamente
                    return {"is_ambiguous": False}

                return {
                    "is_ambiguous": True,
                    "ambiguity_context": (
                        ambiguity_declaration.clarifying_question
                        or " — ".join(ambiguity_declaration.ambiguous_topics)
                        or "Solicitud ambigua detectada"
                    ),
                    "signals": ambiguity_declaration.ambiguous_topics,
                    "confidence": 0.9
                    if ambiguity_declaration.clarifying_question
                    else 0.7,
                }

            # Declaración explícita: no hay ambigüedad
            return {"is_ambiguous": False}

        # PRIORIDAD 2: Sin declaración estructurada — safe default
        # (no detectar ambigüedad falsa por falta de datos)
        return {"is_ambiguous": False}
