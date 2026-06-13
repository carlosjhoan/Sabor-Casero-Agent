"""
summarize skill — session summarization with completion guard (Task 6.5).

Provides fire-and-forget session summarization with a 5-second timeout
guard. On timeout, a synchronous fallback summary is written immediately
with turn data only (no LLM).
"""
import asyncio
import logging
from typing import Any, Optional

from src.core.agent.skill_base import BaseSkill
from src.core.agent.stage_result import SkillResult

logger = logging.getLogger(__name__)

FALLBACK_SUMMARIZATION_TIMEOUT_S = 5.0


class Skill(BaseSkill):
    """Session summarization with completion guard and sync fallback."""
    name = "summarize"
    version = "0.1.0"

    def load(self, context: Any) -> None:
        """Store reference to ContextSummarizer."""
        ctx = context or {}
        self._summarizer = ctx.get("summarizer")
        self._timeout = getattr(ctx.get("settings"), "summarization_timeout", FALLBACK_SUMMARIZATION_TIMEOUT_S)

    async def run(self, input_data: Any) -> SkillResult:
        """Run session summarization with completion guard.

        Input::
            {
                "session_id": str,
                "turn_number": int,
                "message": str,
                "focuses": list,
                "intents": list,
                "summary_order": str,
                "assistant_response": str,
            }

        Returns::
            {
                "success": bool,          # Whether a summary was written
                "fallback_used": bool,    # Whether sync fallback was used
            }
        """
        from src.core.agent.exceptions import StageExecutionError

        try:
            session_id = input_data.get("session_id", "")
            turn_number = input_data.get("turn_number", 0)
            message = input_data.get("message", "")
            focuses = input_data.get("focuses", [])
            intents = input_data.get("intents", [])
            summary_order = input_data.get("summary_order", "")
            assistant_response = input_data.get("assistant_response", "")

            if not session_id:
                return SkillResult.ok(
                    value={"success": False, "fallback_used": False},
                    skill_name=self.name,
                    skill_version=self.version,
                )

            if self._summarizer is None:
                # No summarizer — write sync fallback
                await self._write_fallback(
                    session_id, turn_number, message, summary_order, assistant_response
                )
                return SkillResult.ok(
                    value={"success": True, "fallback_used": True},
                    skill_name=self.name,
                    skill_version=self.version,
                )

            # Attempt summarization with timeout guard (S-P6-02)
            try:
                async with asyncio.timeout(self._timeout):
                    success = await self._summarizer.summarize_turn(
                        session_id=session_id,
                        turn_number=turn_number,
                        user_message=message,
                        focus="; ".join(focuses) if focuses else "",
                        intents=intents,
                        order_state=summary_order,
                        assistant_response=assistant_response,
                    )
                return SkillResult.ok(
                    value={"success": success, "fallback_used": False},
                    skill_name=self.name,
                    skill_version=self.version,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "Summarization timed out after %.1fs — writing sync fallback",
                    self._timeout,
                )
                await self._write_fallback(
                    session_id, turn_number, message, summary_order, assistant_response
                )
                return SkillResult.ok(
                    value={"success": True, "fallback_used": True},
                    skill_name=self.name,
                    skill_version=self.version,
                )

        except Exception as e:
            return SkillResult.fail(
                skill_name=self.name,
                skill_version=self.version,
                error=StageExecutionError(
                    f"Summarization failed: {e}",
                    stage_name=self.name,
                    original_exception=e if isinstance(e, Exception) else None,
                ),
            )

    async def _write_fallback(
        self,
        session_id: str,
        turn_number: int,
        message: str,
        summary_order: str,
        assistant_response: str = "",
    ) -> None:
        """Write a synchronous fallback summary."""
        from src.core.memory.domain.models import ConversationSummary

        if self._summarizer is None or not hasattr(self._summarizer, "repo"):
            return

        try:
            fallback = ConversationSummary(
                session_id=session_id,
                turn_number=turn_number,
                summary_text=(
                    f"Turno {turn_number}: {message[:80]}... | "
                    f"Asistente: {assistant_response[:80]}..."
                ) if assistant_response else f"Turno {turn_number}: {message[:80]}...",
                previous_summary="",  # Cannot load previous without LLM
                current_order_state=summary_order or "En proceso",
                source_turns=[turn_number],
                tokens_estimated=10,
            )
            await self._summarizer.repo.save(fallback)
        except Exception as e:
            logger.warning("Failed to write fallback summary: %s", e)

    def unload(self) -> None:
        self._summarizer = None
