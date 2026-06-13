"""
order-flow skill — wrapper around OrderOrchestrator + ActionPlanner (Task 6.2).

Handles order CRUD operations: create, modify, confirm, cancel items.
Wraps OrderOrchestrator.process_order_intent() with SkillResult.
"""
from typing import Any, Optional

from src.core.agent.skill_base import BaseSkill
from src.core.agent.stage_result import SkillResult


class Skill(BaseSkill):
    """Order processing via OrderOrchestrator and ActionPlanner."""
    name = "order-flow"
    version = "0.1.0"

    def load(self, context: Any) -> None:
        """Store reference to OrderOrchestrator."""
        ctx = context or {}
        self._orchestrator = ctx.get("order_orchestrator")

    async def run(self, input_data: Any) -> SkillResult:
        """Process ordering intent through the orchestrator.

        Input::
            {
                "ordering_segments": list,   # Segments with ordering intent
                "session_id": str,            # Current session
                "summary_conversation": str,  # Conversation summary
            }

        Returns::
            {
                "orchestrator_response": dict,  # Result from process_order_intent
                "order_after": dict | None,     # Serialized order after processing
            }
        """
        from src.core.agent.exceptions import StageExecutionError

        try:
            ordering_segments = input_data.get("ordering_segments", [])
            session_id = input_data.get("session_id", "")
            summary_conversation = input_data.get("summary_conversation", "")

            if not ordering_segments:
                return SkillResult.ok(
                    value={"orchestrator_response": {}, "order_after": None},
                    skill_name=self.name,
                    skill_version=self.version,
                )

            if self._orchestrator is None:
                return SkillResult.fail(
                    skill_name=self.name,
                    skill_version=self.version,
                    error=StageExecutionError(
                        "OrderOrchestrator not configured",
                        stage_name=self.name,
                    ),
                )

            orchestrator_response = await self._orchestrator.process_order_intent(
                ordering_segments=ordering_segments,
                session_id=session_id,
                summary_conversation=summary_conversation,
            )

            # Reload session to get updated order
            order_after = None
            try:
                session_after = self._orchestrator.action_planner.session_repository.get_session(
                    session_id=session_id
                )
                order_id = session_after.order_id if session_after else None
                if order_id:
                    order = self._orchestrator.action_planner.order_repository.get_order_by_id(
                        order_id=order_id
                    )
                    order_after = order.model_dump() if order else None
            except Exception:
                # Best-effort order reload
                pass

            return SkillResult.ok(
                value={
                    "orchestrator_response": orchestrator_response,
                    "order_after": order_after,
                },
                skill_name=self.name,
                skill_version=self.version,
            )

        except Exception as e:
            return SkillResult.fail(
                skill_name=self.name,
                skill_version=self.version,
                error=StageExecutionError(
                    f"Order flow failed: {e}",
                    stage_name=self.name,
                    original_exception=e if isinstance(e, Exception) else None,
                ),
            )

    def unload(self) -> None:
        self._orchestrator = None
