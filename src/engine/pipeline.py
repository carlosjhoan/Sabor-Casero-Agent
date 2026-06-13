"""
Framework pipeline stages — linear, always run before skill orchestration.

Each stage is a method on ``Pipeline``, a stateless container that takes
its dependencies explicitly in ``__init__``. Stages return ``StageResult``
and are designed to be individually testable.
"""
from typing import Dict, Optional
import json
import time
import logging

from src.config.environment import settings
from src.engine.stage_result import StageResult, SessionContext
from src.engine.exceptions import PipelineError
from src.core.classifier.input_guard import (
    check_message_quality_fast,
    llm_guard_check,
    truncate_message,
    FALLBACK_ERROR,
)
from src.core.classifier.hybrid import HybridClassifier
from src.core.order.domain.session_repository_interface import SessionData
from src.core.order.domain.models import Order
from src.core.order.application.order_flow_tracker import OrderFlowTracker
from src.core.conversation_log.application.conversation_logger import ConversationLogger
from src.core.memory.infrastructure.json_summary_repository import JsonSummaryRepository
from src.core.order.application.orchestrator import OrderOrchestrator
from ..infrastructure.llm_client import LLMClient

logger = logging.getLogger("RAG-Agent")


class Pipeline:
    """Framework stages that run linearly before skill orchestration.

    Stages:
        1. Input Guard  — message quality heuristics (CRITICAL, no LLM)
        2. Session Prep — load/create session with order & summary context
        3. LLM Guard    — context-aware validation (non-critical)
    """

    def __init__(
        self,
        classifier: HybridClassifier,
        orchestrator: OrderOrchestrator,
        conversation_logger: ConversationLogger,
        llm_client: LLMClient,
        summary_repo: JsonSummaryRepository,
        tracker_cache: Dict[str, OrderFlowTracker],
    ):
        self.classifier = classifier
        self.orchestrator = orchestrator
        self.logger = conversation_logger
        self.llm_client = llm_client
        self.summary_repo = summary_repo
        self._tracker_cache = tracker_cache

    # ------------------------------------------------------------------
    # Stage 0: Input Guard
    # ------------------------------------------------------------------

    async def input_guard(self, message: str) -> StageResult[str]:
        """
        CRITICAL: validate message quality before pipeline execution.

        Fast heuristics only (no LLM, no I/O). Returns truncated message
        on success. On rejection, ``error_message`` contains JSON with
        ``guard_rejection`` details.
        """
        stage_name = "STAGE 0: Input Guard"
        stage_start = time.time()

        guard_result = check_message_quality_fast(message)
        if not guard_result.is_valid:
            elapsed = time.time() - stage_start
            logger.info(f"Input guard rejected (fast): {guard_result.reason}")
            print_section(stage_name, f"outcome: rejected ({guard_result.reason}) | time: {elapsed:.3f}s")
            return StageResult.fail(json.dumps({
                "type": "guard_rejected",
                "reason": guard_result.reason,
                "fallback_response": guard_result.fallback_response,
            }, ensure_ascii=False))

        message = truncate_message(message, max_length=800)
        elapsed = time.time() - stage_start
        print_section(stage_name, f"outcome: passed | time: {elapsed:.3f}s")
        return StageResult.ok(message)

    # ------------------------------------------------------------------
    # Stage 1: Session Prep
    # ------------------------------------------------------------------

    async def prepare_session(
        self, session_id: str, user_id: str, message: str
    ) -> StageResult[SessionContext]:
        """
        NON-CRITICAL: prepare session context.

        Returns ``SessionContext`` with session data, order info, and
        conversation summaries. On failure, continues with defaults.
        """
        stage_name = "STAGE 1: Session Prep"
        stage_start = time.time()
        try:
            if self.orchestrator:
                session_repo = self.orchestrator.action_planner.session_repository

                session = session_repo.get_session(session_id=session_id)
                if session is None:
                    session = session_repo.create_session(session_id=session_id)
                    print_section(head="Nueva sesión creada (auto)", msg=session_id)

                session_repo.update_session(session_id=session_id, new_turn=True)
                session = session_repo.get_session(session_id=session_id)
            else:
                session = SessionData(session_id=session_id)

            if self.logger:
                await self.logger.start_interaction(
                    session_id=session_id, user_message=message, user_id=user_id
                )

            order_id = session.order_id
            order: Order = None
            summary_order = "El cliente no ha realizado pedido"

            last_summary = await self.summary_repo.get_latest(session_id=session_id)
            summary_conversation = (
                last_summary.summary_text
                if last_summary
                else "No conversation summary available."
            )

            if order_id and self.orchestrator:
                order = self.orchestrator.action_planner.order_repository.get_order_by_id(
                    order_id=order_id
                )
                summary_order = order.to_summary()

            order_before = order.model_dump() if order else None

            ctx = SessionContext(
                session=session,
                order_id=order_id,
                order=order,
                summary_order=summary_order,
                summary_conversation=summary_conversation,
                order_before=order_before,
            )

            elapsed = time.time() - stage_start
            print_section(stage_name, f"outcome: ready | time: {elapsed:.3f}s")
            return StageResult.ok(ctx)

        except (ConnectionError, TimeoutError, FileNotFoundError) as e:
            elapsed = time.time() - stage_start
            logger.warning(f"Session preparation failed (non-critical): {e}")
            print_section(stage_name, f"outcome: failed (continuing with defaults) | time: {elapsed:.3f}s")
            return StageResult.fail(f"SessionPrepError: {e}")
        except Exception as e:
            elapsed = time.time() - stage_start
            logger.warning(f"Session preparation unexpected error (non-critical): {e}")
            print_section(stage_name, f"outcome: failed (continuing with defaults) | time: {elapsed:.3f}s")
            return StageResult.fail(f"SessionPrepError: {e}")

    # ------------------------------------------------------------------
    # Stage 2: LLM Guard
    # ------------------------------------------------------------------

    async def llm_guard(
        self,
        message: str,
        summary_conversation: str,
        summary_order: str,
        tracker: Optional[OrderFlowTracker] = None,
    ) -> StageResult[str]:
        """
        NON-CRITICAL: LLM-based context-aware validation.

        Runs AFTER session prep so it has conversation and order context.
        On failure the message is allowed through.
        """
        stage_name = "STAGE 2: LLM Guard"
        stage_start = time.time()
        try:
            docs_summaries = self.classifier.doc_registry.get_all_summaries()
            context_parts = []
            if summary_conversation and summary_conversation != "No conversation summary available.":
                context_parts.append(f"Resumen de la conversación: {summary_conversation}")
            if summary_order and summary_order != "El cliente no ha realizado pedido":
                context_parts.append(f"Estado del pedido: {summary_order}")
            if tracker and tracker.last_asked:
                context_parts.append(
                    f"Último campo solicitado al cliente: {tracker.last_asked}"
                )
            if (
                summary_conversation
                and "no ha realizado pedido" in summary_conversation.lower()
                and summary_order
                and summary_order != "El cliente no ha realizado pedido"
            ):
                context_parts.append(
                    "NOTA: El resumen de conversación está desactualizado. "
                    "El estado del pedido indicado arriba es el correcto."
                )
            conversation_context = "\n".join(context_parts)

            guard_result = await llm_guard_check(
                message, self.llm_client, settings, docs_summaries,
                conversation_context=conversation_context
            )

            if not guard_result.is_valid:
                elapsed = time.time() - stage_start
                logger.info(f"Input guard rejected (LLM): {guard_result.reason}")
                print_section(stage_name, f"outcome: rejected ({guard_result.reason}) | time: {elapsed:.3f}s")
                return StageResult.fail(json.dumps({
                    "type": "guard_rejected",
                    "reason": guard_result.reason,
                    "fallback_response": guard_result.fallback_response,
                }, ensure_ascii=False))

            elapsed = time.time() - stage_start
            print_section(stage_name, f"outcome: passed | time: {elapsed:.3f}s")
            return StageResult.ok(message)

        except (ConnectionError, TimeoutError, ValueError) as e:
            elapsed = time.time() - stage_start
            logger.warning(f"LLM guard failed (non-critical): {e}, allowing message through")
            print_section(stage_name, f"outcome: failed (non-critical, allowing through) | time: {elapsed:.3f}s")
            return StageResult.ok(message)
        except Exception as e:
            elapsed = time.time() - stage_start
            logger.warning(f"LLM guard unexpected error (non-critical): {e}, allowing message through")
            print_section(stage_name, f"outcome: unexpected error (non-critical, allowing through) | time: {elapsed:.3f}s")
            return StageResult.ok(message)


# =============================================================================
# Helpers
# =============================================================================

def print_section(head: str, msg: str = "", symbol: str = "▬") -> None:
    """Print a pipeline section header with timing."""
    from src.utils.utils import print_section as _ps
    _ps(head=head, msg=msg, symbol=symbol)
