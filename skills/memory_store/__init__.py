"""
memory-store skill — turn persistence + entity extraction (Task 6.4).

Persists conversation turns to episodic memory and extracts structured
entities (dietary restrictions, preferences, etc.) via MemoryHub.
"""
from typing import Any, Optional

from src.core.agent.skill_base import BaseSkill
from src.core.agent.stage_result import SkillResult
from src.core.memory.domain.models_memory import ConversationTurn


class Skill(BaseSkill):
    """Turn persistence and entity extraction via MemoryHub."""
    name = "memory-store"
    version = "0.1.0"

    def load(self, context: Any) -> None:
        """Store reference to MemoryHub."""
        ctx = context or {}
        self._memory_hub = ctx.get("memory_hub")

    async def run(self, input_data: Any) -> SkillResult:
        """Persist turn and extract entities.

        Input::
            {
                "user_id": str,
                "session_id": str,
                "turn_number": int,
                "user_message": str,
                "assistant_response": str,
            }

        Returns::
            {
                "entities_stored": int,      # Number of entities extracted
                "episode_id": str | None,    # Episode identifier
            }
        """
        from src.core.agent.exceptions import StageExecutionError

        try:
            user_id = input_data.get("user_id", "")
            session_id = input_data.get("session_id", "")
            turn_number = input_data.get("turn_number", 0)
            user_message = input_data.get("user_message", "")
            assistant_response = input_data.get("assistant_response", "")

            if not user_message:
                return SkillResult.ok(
                    value={"entities_stored": 0, "episode_id": None},
                    skill_name=self.name,
                    skill_version=self.version,
                )

            if self._memory_hub is None:
                # Graceful degradation — no memory hub configured
                return SkillResult.ok(
                    value={"entities_stored": 0, "episode_id": None},
                    skill_name=self.name,
                    skill_version=self.version,
                )

            # Build conversation turn
            turn = ConversationTurn(
                user_id=user_id,
                session_id=session_id,
                turn_number=turn_number,
                user_message=user_message,
                assistant_response=assistant_response,
            )

            # Extract entities from the turn
            entities = self._memory_hub.semantic.extract_from_turn(turn)
            for entity in entities:
                self._memory_hub.store(entity)

            return SkillResult.ok(
                value={
                    "entities_stored": len(entities),
                    "episode_id": session_id,
                },
                skill_name=self.name,
                skill_version=self.version,
            )

        except Exception as e:
            return SkillResult.fail(
                skill_name=self.name,
                skill_version=self.version,
                error=StageExecutionError(
                    f"Memory store failed: {e}",
                    stage_name=self.name,
                    original_exception=e if isinstance(e, Exception) else None,
                ),
            )

    def unload(self) -> None:
        self._memory_hub = None
