"""
response-build skill — wrapper around ResponseBuilder (Task 6.3).

Generates final hybrid responses combining order state, RAG results,
and brand voice via the ResponseBuilder.
"""
from typing import Any, Optional

from src.core.agent.skill_base import BaseSkill
from src.core.agent.stage_result import SkillResult

FALLBACK_ERROR = "Lo siento, no pude generar una respuesta. Por favor intenta de nuevo."


class Skill(BaseSkill):
    """Hybrid response generation via ResponseBuilder."""
    name = "response-build"
    version = "0.1.0"

    def load(self, context: Any) -> None:
        """Store reference to ResponseBuilder."""
        ctx = context or {}
        self._builder = ctx.get("response_builder")

    async def run(self, input_data: Any) -> SkillResult:
        """Generate final assistant response.

        Input::
            {
                "classification": UserQueryClassifier,
                "order_state": dict | None,
                "orchestrator_result": dict,
                "message": str,
                "summary_conversation": str,
                "tracker": Any | None,
                "extracted_info": list,  # Results from RAG pipeline
            }

        Returns::
            {
                "response": str,  # Final assistant response
            }
        """
        from src.core.agent.exceptions import StageExecutionError

        try:
            if self._builder is None:
                return SkillResult.fail(
                    skill_name=self.name,
                    skill_version=self.version,
                    error=StageExecutionError(
                        "ResponseBuilder not configured",
                        stage_name=self.name,
                    ),
                )

            classification = input_data.get("classification")
            order_state = input_data.get("order_state")
            orchestrator_result = input_data.get("orchestrator_result", {})
            message = input_data.get("message", "")
            summary_conversation = input_data.get("summary_conversation", "")
            tracker = input_data.get("tracker")
            extracted_info = input_data.get("extracted_info", [])
            user_preferences_context = input_data.get("user_preferences_context", "")

            # Inject tracker into order builder if active
            if tracker and hasattr(self._builder, "order_builder"):
                self._builder.order_builder.tracker = tracker

            response = await self._builder.build_hybrid(
                classification=classification,
                order_state=order_state,
                orchestrator_result=orchestrator_result,
                user_message=message,
                conversation_history=summary_conversation,
                extracted_info=extracted_info,
                brand_voice_path=input_data.get("brand_voice_path", ""),
                prompt_template_path=input_data.get("prompt_template_path", ""),
                settings=input_data.get("settings"),
                user_preferences_context=user_preferences_context,
            )

            # Empty response guard (FR-P1-03)
            if not response or not response.strip():
                response = FALLBACK_ERROR

            return SkillResult.ok(
                value={"response": response},
                skill_name=self.name,
                skill_version=self.version,
            )

        except Exception as e:
            return SkillResult.fail(
                skill_name=self.name,
                skill_version=self.version,
                error=StageExecutionError(
                    f"Response generation failed: {e}",
                    stage_name=self.name,
                    original_exception=e if isinstance(e, Exception) else None,
                ),
            )

    def unload(self) -> None:
        self._builder = None
