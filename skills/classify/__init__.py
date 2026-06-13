"""
classify skill — wrapper around HybridClassifier (Task 6.1).

Provides intent + topic classification for the skill-based architecture.
Wraps HybridClassifier.classify() with error isolation and SkillResult.
"""
from typing import Any, Optional

from src.core.agent.skill_base import BaseSkill
from src.core.agent.stage_result import SkillResult


class Skill(BaseSkill):
    """Intent + topic classification via HybridClassifier."""
    name = "classify"
    version = "0.1.0"

    def load(self, context: Any) -> None:
        """Store reference to HybridClassifier."""
        ctx = context or {}
        self._classifier = ctx.get("classifier")

    async def run(self, input_data: Any) -> SkillResult:
        """Classify user message.

        Input::
            {
                "message": str,               # User message text
                "summary_order": str,         # Current order summary
                "summary_conversation": str,  # Conversation summary
            }

        Returns::
            {
                "classification": dict,       # UserQueryClassifier.model_dump()
                "requires_RAG": bool,
                "requires_reconcilier": bool,
            }
        """
        from src.core.agent.exceptions import StageExecutionError

        try:
            message = input_data.get("message", "")
            summary_order = input_data.get("summary_order", "")
            summary_conversation = input_data.get("summary_conversation", "")
            user_preferences_context = input_data.get("user_preferences_context", "")

            if not message:
                return SkillResult.ok(
                    value={"classification": {}, "requires_RAG": False, "requires_reconcilier": False},
                    skill_name=self.name,
                    skill_version=self.version,
                )

            if self._classifier is None:
                return SkillResult.fail(
                    skill_name=self.name,
                    skill_version=self.version,
                    error=StageExecutionError(
                        "Classifier not configured",
                        stage_name=self.name,
                    ),
                )

            classification = await self._classifier.classify(
                message, summary_order, summary_conversation, user_preferences_context
            )

            return SkillResult.ok(
                value={
                    "classification": classification.model_dump() if hasattr(classification, "model_dump") else classification,
                    "requires_RAG": getattr(classification, "requires_RAG", False),
                    "requires_reconcilier": getattr(classification, "requires_reconcilier", False),
                },
                skill_name=self.name,
                skill_version=self.version,
            )

        except Exception as e:
            return SkillResult.fail(
                skill_name=self.name,
                skill_version=self.version,
                error=StageExecutionError(
                    f"Classification failed: {e}",
                    stage_name=self.name,
                    original_exception=e if isinstance(e, Exception) else None,
                ),
            )

    def unload(self) -> None:
        self._classifier = None
