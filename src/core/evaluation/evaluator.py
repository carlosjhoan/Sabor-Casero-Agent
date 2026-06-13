"""
LLM-as-Judge evaluator — post-response quality assessment.

Phase 1: Observer mode. Runs as fire-and-forget background task.
Evaluates responses across correctness, brand voice, completeness,
order handling, and safety criteria.
"""

import logging

from .models import EvaluationResult
from src.config.environment import settings
from src.infrastructure.llm_client import get_llm_client_for_stage


logger = logging.getLogger(__name__)


class Evaluator:
    """LLM-as-judge evaluator for assistant responses.

    Uses a single LLM call with structured output to assess all
    criteria at once, then computes the overall score.
    """

    def __init__(self, llm_client=None):
        self.llm_client = llm_client or get_llm_client_for_stage("classifier")

    async def evaluate(
        self,
        user_message: str,
        assistant_response: str,
        order_summary: str = "",
        conversation_summary: str = "",
        brand_voice: str = "",
        trace_id: str = "",
    ) -> EvaluationResult:
        """Run all evaluation criteria against the response.

        Args:
            user_message: The original user message.
            assistant_response: The assistant's generated response.
            order_summary: Current order state summary, if any.
            conversation_summary: Conversation history summary, if any.
            brand_voice: Brand voice template content, if available.
            trace_id: Langfuse trace ID for correlation.

        Returns:
            EvaluationResult with per-criterion scores and overall score.
        """
        from src.infrastructure.prompt_manager import get_prompt_manager

        prompt = get_prompt_manager(settings.prompt_fallback_map).get(
            "judge",
            user_message=user_message,
            assistant_response=assistant_response,
            order_summary=order_summary or "Sin pedido activo",
            conversation_summary=conversation_summary or "Sin historial",
            brand_voice=brand_voice or "No disponible",
        )

        result = await self.llm_client.chat_completion(
            messages=[{"role": "system", "content": prompt}],
            model=settings.judge_model,
            temperature=0.0,
            output_format=EvaluationResult,
            stream=False,
        )

        # Ensure the result is an EvaluationResult instance
        if isinstance(result, dict):
            result = EvaluationResult(**result)
        elif not isinstance(result, EvaluationResult):
            logger.warning(
                "Evaluation parse error: got %s, returning fallback",
                type(result).__name__,
            )
            return EvaluationResult(
                scores=[],
                overall_score=0.0,
                summary=f"Evaluation parse error: {type(result).__name__}",
                passed=False,
                trace_id=trace_id,
            )

        result.trace_id = trace_id
        return result
