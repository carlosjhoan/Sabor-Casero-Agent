"""
Input Guard - Pre-classification gate for message quality validation.

Fast heuristics + LLM guard for context-aware validation.
"""
import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class GuardResult:
    """Result of input guard validation."""
    is_valid: bool
    reason: Optional[str] = None
    fallback_response: Optional[str] = None


FALLBACK_GIBBERISH = "Lo siento, no entendí tu mensaje. ¿Podrías repetirlo de forma más clara?"
FALLBACK_EMPTY = "Por favor, escribe tu mensaje para poder ayudarte."
FALLBACK_ERROR = "Disculpa, estoy teniendo problemas para procesar tu solicitud. Por favor intenta de nuevo."


def check_message_quality_fast(message: str) -> GuardResult:
    """
    Fast heuristic checks (no LLM, no I/O).
    
    Returns GuardResult immediately if message fails fast checks.
    """
    msg = message.strip()
    
    if not msg:
        return GuardResult(
            is_valid=False,
            reason="mensaje_vacio",
            fallback_response=FALLBACK_EMPTY
        )
    
    if len(msg) < 2:
        return GuardResult(
            is_valid=False,
            reason="mensaje_muy_corto",
            fallback_response="Tu mensaje es muy corto. ¿Podrías escribir más?"
        )
    
    if re.search(r'(.)\1{5,}', msg):
        return GuardResult(
            is_valid=False,
            reason="caracteres_repetidos",
            fallback_response=FALLBACK_GIBBERISH
        )
    
    return GuardResult(is_valid=True)


async def llm_guard_check(
    message: str,
    llm_client,
    settings,
    docs_summaries: str = "",
    conversation_context: str = ""
) -> GuardResult:
    """
    LLM-based guard for context-aware validation.

    Uses the same LLM as classifier for consistency.
    Business scope is defined dynamically by docs_summaries from DocumentRegistry.
    Conversation context provides the last assistant response or summary so the
    guard can evaluate whether the user's message is a valid conversational reply.
    """
    from src.infrastructure.llm_client import get_model_for_stage

    scope = f" sobre el negocio:\n{docs_summaries}" if docs_summaries else ""
    context = f"\n\nContexto de la conversación:\n{conversation_context}" if conversation_context else ""

    prompt = f"""Eres un guardián de un negocio{scope}.
{context}
Basado en el contexto de la conversación, determina si el mensaje del
usuario es relevante para el negocio o no.

REGLAS:
- Un mensaje con typos leves (ej: "lom,o" en vez de "lomo", "nasado"
  en vez de "asado") es RELEVANTE si la intención es clara.
- Un mensaje sobre modificar un pedido existente es SIEMPRE relevante.
- Un mensaje sobre métodos de pago, dirección, horarios es SIEMPRE relevante.
- Solo rechazar mensajes claramente irrelevantes, publicidad, spam,
  o contenido ofensivo.
- Ante la duda, aceptar.

Responde solo "true" o "false".

Mensaje del usuario: {message}"""

    try:
        response = await llm_client.chat_completion(
            messages=[{"role": "system", "content": prompt}],
            temperature=0.0,
            model=get_model_for_stage("classifier", settings),
            stream=False
        )

        result = response.strip().lower()

        if result == "true":
            return GuardResult(is_valid=True)
        elif result == "false":
            return GuardResult(
                is_valid=False,
                reason="fuera_de_contexto",
                fallback_response=FALLBACK_GIBBERISH
            )
        else:
            logger.warning(f"LLM guard returned unexpected value: {response}, allowing through")
            return GuardResult(is_valid=True)

    except Exception as e:
        import logging
        logging.getLogger("RAG-Agent").warning(f"LLM guard failed: {e}, allowing message through")
        return GuardResult(is_valid=True)


def truncate_message(message: str, max_length: int = 800) -> str:
    """
    Truncate message to max_length to ensure LLM has headroom for JSON output.
    """
    if len(message) <= max_length:
        return message
    return message[:max_length].rsplit(' ', 1)[0] + "..."


import logging

logger = logging.getLogger("RAG-Agent")