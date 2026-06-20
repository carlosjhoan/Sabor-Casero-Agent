"""
Main assistant class — skill-based orchestration (P6)
"""
from typing import Dict, Any, Optional

import asyncio
import json
import time
import logging

from .classifier.hybrid import HybridClassifier
from .classifier.input_guard import FALLBACK_ERROR
from ..infrastructure.llm_client import LLMClient, get_llm_client_for_stage
from .extractor.retriever_interface import RetrieverInterface
from src.config.environment import settings

from src.core.order.application.orchestrator import OrderOrchestrator

from src.core.conversation_log.application.conversation_logger import ConversationLogger
from src.core.memory.infrastructure.json_summary_repository import JsonSummaryRepository
from src.core.memory.application.context_summarizer import ContextSummarizer

from src.utils.utils import print_section
from src.utils.pipeline_streamer import PipelineStreamer, Style, wprint

from src.engine.pipeline import Pipeline
from src.engine.stage_result import StageResult, SkillResult, SessionContext
from src.engine.orchestrator import SkillOrchestrator
from src.engine.skill_registry import SkillRegistry
from src.engine.checkpoint import CheckpointManager, Checkpoint
from src.engine.trace_context import new_trace_id, span
from src.engine.exceptions import PipelineError
from src.engine.planner import Planner, PlannerContext
from src.core.memory.domain.memory_hub import MemoryHub
from .evaluation.evaluator import Evaluator

from langfuse import observe, propagate_attributes


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("RAG-Agent")


class SaborCaseroAssistant:
    """
    Main assistant — skill-based orchestration.

    Framework stages (always run):
        Input Guard → Session Prep → LLM Guard

    Skill orchestration (loaded on demand by SkillOrchestrator):
        classify (always) → domain skills (menu-query, rag-retrieve, order-flow)
        → response-build (always) → memory-store (always) → summarize (fire-and-forget)
    """

    def __init__(
        self,
        extractor: RetrieverInterface = None,
        order_orchestrator: OrderOrchestrator = None,
        logger_conversation: ConversationLogger = None,
        llm_client: LLMClient = None,
        skill_registry: SkillRegistry = None,
        skill_orchestrator: SkillOrchestrator = None,
        checkpoint_manager: CheckpointManager = None,
        memory_hub: MemoryHub = None,
    ):
        """Initialize the assistant with skill-based orchestration components."""
        if llm_client is None:
            llm_client = get_llm_client_for_stage("classifier")
        self.llm_client = llm_client

        # Core domain components (injected into skills via _load_skill context)
        self.classifier = HybridClassifier(llm_client=self.llm_client)
        # Default to LLM-based extractor when no external RAG infrastructure is configured
        if extractor is None:
            from src.core.extractor.llm_extractor import InformationLlmExtractor
            extractor = InformationLlmExtractor(client=llm_client)
        self.extractor = extractor
        self.orchestrator = order_orchestrator
        self.logger = logger_conversation

        # Summarization (injected into memory-store + summarize skills)
        self.summary_repo = JsonSummaryRepository(base_path=settings.summaries_path)
        self.summarizer = ContextSummarizer(summary_repo=self.summary_repo)

        # ── Skill-based architecture ────────────────────────────────────
        self._skill_registry = skill_registry or SkillRegistry()
        if not skill_registry:
            self._skill_registry.discover("skills/")
        self._skill_orchestrator = skill_orchestrator or SkillOrchestrator(self._skill_registry)
        self._checkpoint_manager = checkpoint_manager or CheckpointManager()
        self._memory_hub = memory_hub or MemoryHub()
        self._concurrency_semaphore = asyncio.Semaphore(5)
        
        # Cross-turn planner history cache
        self._last_planner_history: list = []

        # Inject MemoryHub into summarizer for entity extraction
        self.summarizer.set_memory_hub(self._memory_hub)

        # ── Evaluation (observer mode, fire-and-forget) ────────────────
        self.evaluator = Evaluator(llm_client=self.llm_client)

        # ── Pipeline (framework stages) ──────────────────────────────
        self._pipeline = Pipeline(
            classifier=self.classifier,
            orchestrator=self.orchestrator,
            conversation_logger=self.logger,
            llm_client=self.llm_client,
            summary_repo=self.summary_repo,
        )

    # =========================================================================
    # FRAMEWORK STAGES (delegated to self._pipeline)
    # =========================================================================

    async def _stage_input_guard(self, message: str) -> StageResult[str]:
        return await self._pipeline.input_guard(message)

    async def _stage_llm_guard(
        self, message: str, summary_conversation: str, summary_order: str,
    ) -> StageResult[str]:
        return await self._pipeline.llm_guard(
            message, summary_conversation, summary_order
        )

    async def _stage_prepare_session(
        self, session_id: str, user_id: str, message: str
    ) -> StageResult[SessionContext]:
        return await self._pipeline.prepare_session(session_id, user_id, message)

    # =========================================================================
    # SKILL-BASED ORCHESTRATION LOOP (P6)
    # =========================================================================

    async def _run_orchestration_loop(
        self,
        user_id: str,
        message: str,
        session_id: str,
        session_ctx: SessionContext,
        streamer: PipelineStreamer = None,
    ) -> Dict[str, Any]:
        """
        Skill-based orchestration loop.

        Flow:
          1. Framework: Input Guard, Session Prep, LLM Guard (already run by caller)
          2. Skill: classify (always)
          3. Orchestrator decide → domain skills (menu-query, rag-retrieve, order-flow)
          4. Skill: response-build (always)
          5. Framework: Logging
          6. Skill: memory-store (always, post-response)
          7. Skill: summarize (fire-and-forget with completion guard)
        """
        trace_id = new_trace_id()
        _pipeline_start = time.time()

        # ── Extract session context ─────────────────────────────────────
        ctx = session_ctx
        order_id = ctx.order_id
        order = ctx.order
        summary_order = ctx.summary_order
        summary_conversation = ctx.summary_conversation
        order_before = ctx.order_before

        # ── Load UserPreferences (shared: classify + Planner) ──
        user_preferences_context = ""
        try:
            prefs = UserPreferences.load(user_id)
            if prefs:
                user_preferences_context = prefs.to_prompt_context()
        except Exception as e:
            logger.debug("Could not load user preferences: %s", e)

        # ── Derive candidate item names from the extractor ──────────────
        candidates: list = []
        # Prefer _item_names (set by vector-only factory path) to avoid
        # loading OwlClient when USE_OWL=False.
        owl_client = getattr(self.extractor, "_owl_client", None)
        item_names = getattr(self.extractor, "_item_names", None)
        if item_names:
            candidates = list(item_names)
        else:
            # Fallback: OWL-based item names via OwlClient
            if owl_client:
                try:
                    candidates = list(owl_client.get_item_names())
                except Exception:
                    pass

        # ── Safe defaults for shared post-processing ──
        # Classic path overrides these; Planner path doesn't set them.
        topic_details: list = []
        classification_data: dict = {}
        extracted_info: list = []
        domain_results: dict = {}

        # ════════════════════════════════════════════════════════════════
        # LLM Planner — decides which tools to invoke
        # (classify, order tools, skills) in a loop.
        # ════════════════════════════════════════════════════════════════

        # ── Stateless order checklist for Planner context ─────
        # Computes what order fields have values and what's pending,
        # so the Planner can decide what to ask next.
        order_checklist_status = "No hay pedido activo."
        if self.orchestrator and session_id:
            try:
                order_checklist_status = await self.orchestrator.get_order_checklist(session_id)
            except Exception:
                logger.warning("Failed to compute order checklist", exc_info=True)

        # ── Memory entities for Planner context ────────────────
        # Query semantic memory for entities related to this user.
        memory_entities = ""
        try:
            from src.core.memory.domain.models_memory import RecallContext
            recall = self._memory_hub.recall(RecallContext(
                query=message,
                user_id=user_id,
                top_k=5,
            ))
            if recall.semantic_results:
                items = []
                for e in recall.semantic_results:
                    label = e.get("entity_type", "dato").replace("_", " ")
                    value = e.get("value", "")
                    conf = e.get("confidence", 0)
                    items.append(f"- {label}: {value} (confianza: {conf:.1f})")
                memory_entities = "**Datos recordados del cliente:**\n" + "\n".join(items)
        except Exception:
            logger.debug("Memory recall failed (non-critical)", exc_info=True)

        planner_context = PlannerContext(
            summary_conversation=summary_conversation,
            summary_order=summary_order,
            user_preferences_context=user_preferences_context,
            user_id=user_id,
            session_id=session_id,
            candidates=candidates,
            topic_details=[],  # Empty — Planner decides if it needs classify
            order_checklist_status=order_checklist_status,
            memory_entities=memory_entities,
        )
        planner = Planner(
            llm_client=self.llm_client,
            skill_orchestrator=self._skill_orchestrator,
            streamer=streamer,
            settings=settings,
            registry=self._skill_orchestrator.registry,
            trace_id=trace_id,
            extractor=self.extractor,
            skill_context={
                "classifier": self.classifier,
                "order_orchestrator": self.orchestrator,
                "memory_hub": self._memory_hub,
                "summarizer": self.summarizer,
                "checkpoint_manager": self._checkpoint_manager,
            },
        )
        response_text = await planner.run(
            message, planner_context,
            previous_messages=self._last_planner_history,
        )
        # Cache this turn's messages for the next turn
        self._last_planner_history = planner._messages.copy()
        elapsed_time = time.time() - _pipeline_start

        # Planner replaces domain skills + response-build.
        # extracted_info, domain_results are already set to
        # safe defaults before the fork.
        _skills_msg = f"Planner: {planner.tool_call_count} tool call(s)"

        # On critical failure, return early (consistent with old pipeline)
        if not response_text or response_text == FALLBACK_ERROR:
            return {
                "response": FALLBACK_ERROR,
                "classification": {},
                "extracted_info": [],
                "pipeline_error": "Planner failed to produce response",
            }

        # ── Evaluation (fire-and-forget, observer mode) ──────────────────
        if settings.evaluation_enabled:
            streamer.note("LLM-as-Judge (evaluation)", emoji="📊")
            streamer.fire_and_forget("Judging response quality in background — scores will appear in Langfuse")
            asyncio.create_task(self._run_evaluation(
                user_message=message,
                assistant_response=response_text,
                order_summary=summary_order,
                conversation_summary=summary_conversation,
                trace_id=trace_id,
            ))

        # ── Logging (framework) ─────────────────────────────────────────
        # ponytail: orchestrator_response always {} (classic pipeline removed)
        orchestrator_response = {}

        # Build topic_details list compatible with the logging interface
        log_topic_details = []
        try:
            for td in topic_details:
                log_topic_details.append(td)
        except Exception:
            log_topic_details = topic_details if isinstance(topic_details, list) else []

        # Create a minimal classification-like object for logging
        log_classification = type("LogClassification", (), {
            "topic_details": log_topic_details or [],
        })()

        if self.logger:
            try:
                await self.logger.log_extraction(classification_data.get("topic_details", []))
                await self.logger.log_processor(
                    processor_thought=orchestrator_response.get("thought", "No thoughts provided"),
                    proposed_actions=orchestrator_response.get("actions", []),
                )
                await self.logger.log_result(
                    assistant_response=response_text,
                    order_before=order_before,
                    order_after=None,
                    success=orchestrator_response.get("success", False),
                    error_message=orchestrator_response.get("error_message", None),
                    processing_time_ms=elapsed_time * 1000,
                )
            except (IOError, ConnectionError) as e:
                logger.warning(f"Interaction logging failed (non-critical): {e}")
            except Exception as e:
                logger.warning(f"Interaction logging unexpected error (non-critical): {e}")

        # ── Skill: memory-store (always, post-response) ─────────────────
        if settings.semantic_memory_enabled:
            memory_skill = self._load_skill("memory-store")
            turn_number = getattr(ctx.session, "turn_number", 0) if ctx.session else 0
            with span("memory-store"):
                await memory_skill.execute(
                    {
                        "user_id": user_id,
                        "session_id": session_id,
                        "turn_number": turn_number,
                        "user_message": message,
                        "assistant_response": response_text,
                    },
                    trace_id=trace_id,
                )

        # ── Synchronous fallback summary ──────────────────────────────
        # Ensures the next turn ALWAYS has at least basic conversation context.
        # The fire-and-forget LLM summary below will overwrite this when it
        # completes, but this guarantees no "No conversation summary available."
        # even when background tasks can't run (e.g., CLI blocking on input()).
        focuses = [d.get("focus", "") for d in topic_details] if topic_details else []
        intents_list = list(set([d.get("query_type", "") for d in topic_details])) if topic_details else []
        turn_number = getattr(ctx.session, "turn_number", 0) if ctx.session else 0
        session_id_for_summary = getattr(ctx.session, "session_id", session_id) if ctx.session else session_id

        # Extract item names from RAG pipeline results for richer context
        mentioned_items = []
        for item in (extracted_info or []):
            name = item.get("item_name", "")
            if name and item.get("_type") != "menu_structure":
                mentioned_items.append(name)

        try:
            from src.core.memory.domain.models import ConversationSummary

            def _build_summary_text() -> str:
                lines = [f"  [Turno {turn_number}]"]
                lines.append(f"  usuario: {message[:250]}")
                if response_text:
                    lines.append(f"  asistente: {response_text[:250]}")
                if intents_list:
                    lines.append(f"  intencion: {', '.join(intents_list[:3])}")
                if mentioned_items:
                    lines.append(f"  items: {', '.join(mentioned_items[:6])}")
                return "\n".join(lines)

            sync_fallback = ConversationSummary(
                session_id=session_id_for_summary,
                turn_number=turn_number,
                summary_text=_build_summary_text(),
                previous_summary=(
                    summary_conversation
                    if summary_conversation and summary_conversation != "No conversation summary available."
                    else ""
                ),
                current_order_state=summary_order or "En proceso",
                source_turns=[turn_number],
                tokens_estimated=10,
            )
            await self.summary_repo.save(sync_fallback)
        except Exception as e:
            logger.warning("Failed to write sync fallback summary: %s", e)

        # ── Skill: summarize (fire-and-forget with completion guard) ──
        # This will overwrite the sync fallback with an LLM-generated summary
        # when the event loop has time to process it.
        asyncio.create_task(self._run_summarize_skill(
            session_id=session_id_for_summary,
            turn_number=turn_number,
            message=message,
            focuses=focuses,
            intents=intents_list,
            summary_order=summary_order,
            assistant_response=response_text,
            trace_id=trace_id,
        ))

        # ── Done ────────────────────────────────────────────────────────
        print_section(
            head="⏱️ SKILL PIPELINE COMPLETE",
            msg=f"Total: {elapsed_time:.2f}s | {_skills_msg}",
            symbol="=",
        )

        return {
            "response": response_text,
            "classification": classification_data,
            "extracted_info": extracted_info,
            "trace_id": trace_id,
        }

    def _load_skill(self, name: str):
        """Load or return an already-loaded skill by name."""
        if self._skill_orchestrator.is_loaded(name):
            return self._skill_orchestrator._loaded[name]
        return self._skill_orchestrator.load_skill(name, context={
            "classifier": self.classifier,
            "order_orchestrator": self.orchestrator,
            "memory_hub": self._memory_hub,
            "summarizer": self.summarizer,
            "settings": settings,
            "checkpoint_manager": self._checkpoint_manager,
            "owl_client": getattr(self.extractor, "_owl_client", None),
            "owl_signal": getattr(self.extractor, "_owl_signal", None),
            "retriever": self.extractor,
            "bm25_retriever": getattr(self.extractor, "_bm25", None),
            "entity_retriever": getattr(self.extractor, "_entity", None),
            "rrf_fuser": getattr(self.extractor, "_rrf_fuser", None),
            "cross_encoder": getattr(self.extractor, "_cross_encoder", None),
            "ontology_gate": getattr(self.extractor, "_ontology_gate", None),
        })

    async def _run_summarize_skill(
        self,
        session_id: str,
        turn_number: int,
        message: str,
        focuses: list,
        intents: list,
        summary_order: str,
        assistant_response: str = "",
        trace_id: str = "",
    ):
        """Fire-and-forget: run the summarize skill with completion guard."""
        try:
            summarize_skill = self._load_skill("summarize")
            with span("summarize"):
                result = await summarize_skill.execute(
                    {
                        "session_id": session_id,
                        "turn_number": turn_number,
                        "message": message,
                        "focuses": focuses,
                        "intents": intents,
                        "summary_order": summary_order,
                        "assistant_response": assistant_response,
                    },
                    trace_id=trace_id,
                )
            if result.success:
                fallback = result.value.get("fallback_used", False)
                print_section(
                    head="✅ Summarization complete",
                    msg=f"Fallback: {fallback} | Turn: {turn_number}",
                    symbol="*",
                )
            else:
                logger.warning(f"Summarization skill failed: {result.error}")
        except Exception as e:
            logger.error(f"Background summarization failed: {e}")

    async def _run_evaluation(
        self,
        user_message: str,
        assistant_response: str,
        order_summary: str = "",
        conversation_summary: str = "",
        trace_id: str = "",
    ):
        """Fire-and-forget: evaluate response quality (observer mode).

        Runs asynchronously after the response is sent to the user.
        Scores are pushed to Langfuse via ``langfuse.score()`` for
        dashboard visibility. Failures are logged as warnings — never
        block the response path.
        """
        try:
            brand_voice = ""
            if settings.brand_voice_path:
                try:
                    with open(settings.brand_voice_path, 'r', encoding='utf-8') as f:
                        brand_voice = f.read()
                except Exception:
                    pass

            result = await self.evaluator.evaluate(
                user_message=user_message,
                assistant_response=assistant_response,
                order_summary=order_summary,
                conversation_summary=conversation_summary,
                brand_voice=brand_voice,
                trace_id=trace_id,
            )

            logger.info(
                "Evaluation | trace=%s overall=%.2f passed=%s summary=%s",
                trace_id, result.overall_score, result.passed, result.summary,
            )

            # ── Push scores to Langfuse ────────────────────────────
            # Attach per-criterion scores to the trace for dashboard
            # filtering and alerting. We use score_current_trace() to
            # target the Langfuse trace (via OTel context) rather than
            # our internal trace_id, which is different from Langfuse's
            # auto-generated trace ID.
            if result.scores:
                _push_scores_to_langfuse(result)

        except Exception as e:
            logger.warning("Evaluation failed (non-critical): %s", e)

    # =========================================================================
    # MAIN ENTRY POINT
    # =========================================================================

    @observe(name="process_message")
    async def process_message(
        self, user_id: str, message: str, session_id: str = None
    ) -> Dict[str, Any]:
        """
        Main message processing — skill-based orchestration.

        Flow:
        1. Input Guard (fast) — message quality heuristics (CRITICAL)
        2. Session Prep — load session context (non-critical)
        3. LLM Guard — context-aware validation (non-critical)
        4. Skill orchestration loop — classify → domain skills → response-build
        5. Logging + memory-store + summarize (post-response)
        """
        streamer = PipelineStreamer()

        try:
            # ── Langfuse: propagate session_id/user_id to trace ────────
            with propagate_attributes(
                session_id=session_id or "unknown",
                user_id=user_id,
            ):
                # ── Framework: Input Guard ──────────────────────────────
                with streamer.phase("Input Guard") as p:
                    guard_result = await self._stage_input_guard(message)
                    if not guard_result.success:
                        p.result("Rejected", str(guard_result.error_message or ""), is_error=True)
                        try:
                            info = json.loads(guard_result.error_message or "{}")
                        except (json.JSONDecodeError, TypeError):
                            info = {}
                        if info.get("type") == "guard_rejected":
                            return {
                                "response": info.get("fallback_response", FALLBACK_ERROR),
                                "classification": None,
                                "extracted_info": [],
                                "guard_rejected": True,
                                "reject_reason": info.get("reason", "guard_rejected"),
                            }
                        return {
                            "response": FALLBACK_ERROR,
                            "classification": None,
                            "extracted_info": [],
                            "pipeline_error": guard_result.error_message or "guard_rejected",
                        }
                    p.done(f"Passed — {len(message)} chars")

                message = guard_result.value

                # ── Framework: Session Prep ─────────────────────────────
                with streamer.phase("Session Prep") as p:
                    session_result = await self._stage_prepare_session(
                        session_id, user_id, message
                    )
                    if session_result.success:
                        session_ctx = session_result.value
                        p.info("Order ID", str(session_ctx.order_id or "none"))
                        p.done()
                    else:
                        session_ctx = SessionContext(
                            session=None, order_id=None, order=None,
                            summary_order="El cliente no ha realizado pedido",
                            summary_conversation="No conversation summary available.",
                            order_before=None,
                        )
                        p.result("Fallback", "session context defaulted", is_error=False)

                # ── Framework: LLM Guard ────────────────────────────────
                with streamer.phase("LLM Guard") as p:
                    llm_guard_result = await self._stage_llm_guard(
                        message,
                        session_ctx.summary_conversation,
                        session_ctx.summary_order,
                    )
                    if not llm_guard_result.success:
                        p.result("Rejected", str(llm_guard_result.error_message or ""), is_error=True)
                        try:
                            info = json.loads(llm_guard_result.error_message or "{}")
                        except (json.JSONDecodeError, TypeError):
                            info = {}
                        return {
                            "response": info.get("fallback_response", FALLBACK_ERROR),
                            "classification": None,
                            "extracted_info": [],
                            "guard_rejected": True,
                            "reject_reason": info.get("reason", "guard_rejected"),
                        }
                    p.done("Passed")

                # ── Skill orchestration (with concurrency semaphore) ────
                async with self._concurrency_semaphore:
                    result = await self._run_orchestration_loop(
                        user_id=user_id,
                        message=message,
                        session_id=session_id,
                        session_ctx=session_ctx,
                        streamer=streamer,
                    )
                    # Print response and timing after the pipeline completes
                    if result.get("response") and result["response"] != FALLBACK_ERROR:
                        streamer.response(result["response"])
                    streamer.total()
                    return result

        except PipelineError as e:
            logger.error(f"Pipeline error: {e}")
            return {
                "response": FALLBACK_ERROR,
                "classification": None,
                "extracted_info": [],
                "pipeline_error": str(e),
            }
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            return {
                "response": FALLBACK_ERROR,
                "classification": None,
                "extracted_info": [],
                "pipeline_error": f"PipelineUnexpectedError: {e}",
            }

    # =========================================================================
    # HELPERS
    # =========================================================================

# =============================================================================
# MODULE-LEVEL HELPERS
# =============================================================================


def _push_scores_to_langfuse(result: "EvaluationResult") -> None:
    """Push per-criterion evaluation scores to the current Langfuse trace.

    Uses ``score_current_trace()`` which targets the Langfuse trace
    active in the current OpenTelemetry context (propagated via
    ``contextvars`` through ``asyncio.create_task()``).

    Each criterion becomes a separate score on the trace so the Langfuse
    dashboard can filter, aggregate, and alert on individual dimensions
    (correctness, brand voice, completeness, etc.).

    Args:
        result: The evaluation result containing per-criterion scores.
    """
    try:
        from langfuse import Langfuse

        lf = Langfuse()
        for score in result.scores:
            lf.score_current_trace(
                name=score.criterion.value,
                value=score.score,
                comment=score.reasoning,
            )

        # Also push the overall score as a summary metric
        lf.score_current_trace(
            name="overall",
            value=result.overall_score,
            comment=result.summary,
        )
    except Exception as e:
        logger.warning("Failed to push evaluation scores to Langfuse: %s", e)
