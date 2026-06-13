"""
Main assistant class — skill-based orchestration (P6)
"""
from typing import Dict, Any, Optional

import asyncio
import json
import time
import logging

from .classifier.hybrid import HybridClassifier
from .classifier.input_guard import check_message_quality_fast, llm_guard_check, truncate_message, FALLBACK_ERROR
from .response.response_builder import ResponseBuilder
from ..infrastructure.llm_client import LLMClient, get_llm_client_for_stage
from .classifier.intent import QueryType
from .extractor.retriever_interface import RetrieverInterface
from src.config.environment import settings

from src.core.order.application.orchestrator import OrderOrchestrator
from src.core.order.application.order_flow_tracker import OrderFlowTracker
from src.core.user.preferences import UserPreferences

from .order.domain.session_repository_interface import SessionData
from .order.domain.models import Order

from src.core.conversation_log.application.conversation_logger import ConversationLogger
from src.core.memory.infrastructure.json_summary_repository import JsonSummaryRepository
from src.core.memory.application.context_summarizer import ContextSummarizer

from src.utils.utils import print_section
from src.utils.pipeline_streamer import PipelineStreamer, Style, wprint

from .agent.stage_result import StageResult, SkillResult, SessionContext
from .agent.orchestrator import SkillOrchestrator
from .agent.skill_registry import SkillRegistry
from .agent.checkpoint import CheckpointManager, Checkpoint
from .agent.trace_context import new_trace_id, span
from .agent.exceptions import PipelineError
from .agent.planner import Planner, PlannerContext
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
        self.response_builder = ResponseBuilder(
            llm_client=self.llm_client,
            extractor=extractor,
        )
        self.orchestrator = order_orchestrator
        self.logger = logger_conversation

        # Summarization (injected into memory-store + summarize skills)
        self.summary_repo = JsonSummaryRepository(base_path=settings.summaries_path)
        self.summarizer = ContextSummarizer(summary_repo=self.summary_repo)

        # Tracker cache (per-user_id OrderFlowTracker instances)
        self._tracker_cache: Dict[str, OrderFlowTracker] = {}

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

    # =========================================================================
    # FRAMEWORK STAGES (always run, pre-orchestration)
    # =========================================================================

    async def _stage_input_guard(self, message: str) -> StageResult[str]:
        """
        CRITICAL: validate message quality before pipeline execution.

        Fast heuristics only (no LLM, no I/O). Returns truncated message on success.
        On rejection, error_message contains JSON with guard_rejection details.
        """
        stage_name = "STAGE 0: Input Guard"
        stage_start = time.time()

        guard_result = check_message_quality_fast(message)
        if not guard_result.is_valid:
            elapsed = time.time() - stage_start
            logger.info(f"Input guard rejected (fast): {guard_result.reason}")
            print_section(
                head=stage_name,
                msg=f"outcome: rejected ({guard_result.reason}) | time: {elapsed:.3f}s",
                symbol="▬"
            )
            return StageResult.fail(json.dumps({
                "type": "guard_rejected",
                "reason": guard_result.reason,
                "fallback_response": guard_result.fallback_response
            }, ensure_ascii=False))

        message = truncate_message(message, max_length=800)
        elapsed = time.time() - stage_start
        print_section(
            head=stage_name,
            msg=f"outcome: passed | time: {elapsed:.3f}s",
            symbol="▬"
        )
        return StageResult.ok(message)

    async def _stage_llm_guard(
        self, message: str, summary_conversation: str, summary_order: str,
        tracker: Optional[OrderFlowTracker] = None,
    ) -> StageResult[str]:
        """
        NON-CRITICAL: LLM-based context-aware validation.

        Runs AFTER session prep so it has conversation context and order state.
        On failure, message is allowed through (non-critical).
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
            # Detect stale summary vs real order state
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
                print_section(
                    head=stage_name,
                    msg=f"outcome: rejected ({guard_result.reason}) | time: {elapsed:.3f}s",
                    symbol="▬"
                )
                return StageResult.fail(json.dumps({
                    "type": "guard_rejected",
                    "reason": guard_result.reason,
                    "fallback_response": guard_result.fallback_response
                }, ensure_ascii=False))

            elapsed = time.time() - stage_start
            print_section(
                head=stage_name,
                msg=f"outcome: passed | time: {elapsed:.3f}s",
                symbol="▬"
            )
            return StageResult.ok(message)
        except (ConnectionError, TimeoutError, ValueError) as e:
            elapsed = time.time() - stage_start
            logger.warning(f"LLM guard failed (non-critical): {e}, allowing message through")
            print_section(
                head=stage_name,
                msg=f"outcome: failed (non-critical, allowing through) | time: {elapsed:.3f}s",
                symbol="▬"
            )
            return StageResult.ok(message)
        except Exception as e:
            elapsed = time.time() - stage_start
            logger.warning(f"LLM guard unexpected error (non-critical): {e}, allowing message through")
            print_section(
                head=stage_name,
                msg=f"outcome: unexpected error (non-critical, allowing through) | time: {elapsed:.3f}s",
                symbol="▬"
            )
            return StageResult.ok(message)

    async def _stage_prepare_session(
        self, session_id: str, user_id: str, message: str
    ) -> StageResult[SessionContext]:
        """
        NON-CRITICAL: prepare session context.

        Returns SessionContext with session data, order info, and summaries.
        On failure, continue with default/empty values.
        """
        stage_name = "STAGE 1: Session Prep"
        stage_start = time.time()
        try:
            # Guard: orchestrator may be None when initialized without order_orchestrator
            if self.orchestrator:
                session_repo = self.orchestrator.action_planner.session_repository

                # Auto-create session if it doesn't exist yet (e.g. CLI mode
                # generates a session_id inline without registering it first)
                session = session_repo.get_session(session_id=session_id)
                if session is None:
                    session = session_repo.create_session(session_id=session_id)
                    print_section(head="Nueva sesión creada (auto)", msg=session_id)

                session_repo.update_session(session_id=session_id, new_turn=True)
                session = session_repo.get_session(session_id=session_id)
            else:
                session = SessionData(session_id=session_id)

            # Logger may be None when initialized without logger_conversation
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
            print_section(
                head=stage_name,
                msg=f"outcome: ready | time: {elapsed:.3f}s",
                symbol="▬"
            )
            return StageResult.ok(ctx)
        except (ConnectionError, TimeoutError, FileNotFoundError) as e:
            elapsed = time.time() - stage_start
            logger.warning(f"Session preparation failed (non-critical): {e}")
            print_section(
                head=stage_name,
                msg=f"outcome: failed (continuing with defaults) | time: {elapsed:.3f}s",
                symbol="▬"
            )
            return StageResult.fail(f"SessionPrepError: {e}")
        except Exception as e:
            elapsed = time.time() - stage_start
            logger.warning(f"Session preparation unexpected error (non-critical): {e}")
            print_section(
                head=stage_name,
                msg=f"outcome: failed (continuing with defaults) | time: {elapsed:.3f}s",
                symbol="▬"
            )
            return StageResult.fail(f"SessionPrepError: {e}")

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
        if settings.use_order_flow_tracker:
            try:
                if user_id in self._tracker_cache:
                    prefs = self._tracker_cache[user_id]._user_prefs
                else:
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
        tracker: Optional[OrderFlowTracker] = None

        # ════════════════════════════════════════════════════════════════
        # FORK: LLM Planner vs classic skill pipeline
        # ════════════════════════════════════════════════════════════════
        if settings.use_llm_planner:
            # Planner path — NO mandatory classify.
            # classify is available as an optional tool the Planner can call
            # when the message is complex or has multiple intents.
            # For simple queries (greetings, menu requests, single items),
            # the Planner resolves them directly without classify overhead.

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
                    "response_builder": self.response_builder,
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
            # extracted_info, domain_results, tracker are already set to
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

        else:
            # ── Classic pipeline ─────────────────────────────────────────
            # classify (mandatory in classic path — gates RAG and order-flow)
            phase_name = streamer and streamer.phase("Classification", emoji="🔍")
            if phase_name:
                phase_classify = phase_name.__enter__()
                phase_classify.step(f"Analyzing: \"{message[:60]}{'...' if len(message) > 60 else ''}\"")

            classify_skill = self._load_skill("classify")
            with span("classify"):
                classify_result = await classify_skill.execute(
                    {
                        "message": message,
                        "summary_order": summary_order,
                        "summary_conversation": summary_conversation,
                        "user_preferences_context": user_preferences_context,
                    },
                    trace_id=trace_id,
                )

            if not classify_result.success:
                elapsed_time = time.time() - _pipeline_start
                if phase_name:
                    phase_classify.result("Failed", str(classify_result.error), is_error=True)
                    phase_name.__exit__(None, None, None)
                return {
                    "response": FALLBACK_ERROR,
                    "classification": None,
                    "extracted_info": [],
                    "pipeline_error": str(classify_result.error),
                }

            classification_data = classify_result.value.get("classification", {})
            requires_RAG = classify_result.value.get("requires_RAG", False)
            requires_reconcilier = classify_result.value.get("requires_reconcilier", False)

            # Show classification decisions inline
            if phase_name:
                topic_details_raw = classification_data.get("topic_details", [])
                for td in topic_details_raw[:3]:
                    seg = td.get("segment", "") if isinstance(td, dict) else getattr(td, "segment", "")
                    qtype = td.get("query_type", "") if isinstance(td, dict) else str(getattr(td, "query_type", ""))
                    topic = td.get("topic", "") if isinstance(td, dict) else str(getattr(td, "topic", ""))
                    if seg:
                        phase_classify.info(f"Segment", f"\"{seg}\" → {qtype} / {topic}")
                phase_classify.info("Requires RAG", "yes" if requires_RAG else "no")
                if requires_reconcilier:
                    phase_classify.info("Order flow", "active")
                phase_classify.done(f"{len(topic_details_raw) if isinstance(topic_details_raw, list) else 0} segment(s) classified")
                phase_name.__exit__(None, None, None)

            topic_details = classification_data.get("topic_details", [])
            domain_skill_names: list = []

            if requires_reconcilier:
                domain_skill_names.append("order-flow")

            # ── RAG skills (replaces inline LLM extraction) ─────────────────
            # menu-query = OWL deterministic fast-path
            # rag-retrieve = multi-signal pipeline (dense + BM25 + entity + OWL
            #                → RRF → cross-encoder → ontology gate)
            if requires_RAG:
                domain_skill_names.append("menu-query")
                domain_skill_names.append("rag-retrieve")

            # ── Full-menu request detection ─────────────────────────────────
            if requires_RAG and owl_client and self._is_full_menu_request(topic_details):
                try:
                    full_menu_text = owl_client.get_full_menu()
                    if full_menu_text:
                        extracted_info = [{
                            "_type": "menu_structure",
                            "text": full_menu_text,
                        }]
                        # Remove RAG skills — the menu is already loaded
                        domain_skill_names = [
                            s for s in domain_skill_names
                            if s not in ("menu-query", "rag-retrieve")
                        ]
                        requires_RAG = False
                        logger.info(
                            "Full-menu request detected — bypassing RAG pipeline "
                            "(%d chars formatted)", len(full_menu_text)
                        )
                except Exception as e:
                    logger.warning("Full-menu retrieval failed, falling back to RAG pipeline: %s", e)

            # ── Domain Skills ───────────────────────────────────────────────
            if domain_skill_names:
                phase_domain = streamer.phase("Domain Skills", emoji="⚙️").__enter__()
                phase_domain.step(f"Skills to run: {', '.join(sorted(domain_skill_names))}")

            for skill_name in domain_skill_names:
                skill_instance = self._load_skill(skill_name)
                if skill_name == "order-flow":
                    ordering_segments = self._get_ordering_segments(
                        topic_details if isinstance(topic_details, list) else []
                    )
                    if not ordering_segments:
                        if streamer:
                            phase_domain.result("Skipped", "order-flow — no ordering segments")
                        continue
                    with span(skill_name):
                        skill_result = await skill_instance.execute(
                            {
                                "ordering_segments": ordering_segments,
                                "session_id": session_id,
                                "summary_conversation": summary_conversation,
                            },
                            trace_id=trace_id,
                        )
                    if streamer:
                        if skill_result.success:
                            phase_domain.done(f"order-flow — {len(ordering_segments)} order segment(s)")
                        else:
                            phase_domain.result("Failed", f"order-flow: {skill_result.error}", is_error=True)
                else:
                    # menu-query / rag-retrieve — pass query + candidates + details
                    with span(skill_name):
                        skill_result = await skill_instance.execute(
                            {
                                "query": message,
                                "candidates": candidates,
                                "details": topic_details if isinstance(topic_details, list) else [],
                            },
                            trace_id=trace_id,
                        )
                    if streamer:
                        count = len(skill_result.value.get("items", [])) if skill_result.success else 0
                        if skill_result.success:
                            phase_domain.done(f"{skill_name} — {count} item(s)")
                        else:
                            phase_domain.result("Failed", f"{skill_name}: {skill_result.error}", is_error=True)

                domain_results[skill_name] = skill_result
                if skill_result.success:
                    # Merge new items with existing, deduplicating by item_name
                    new_items = skill_result.value.get("items", [])
                    existing_names = {
                        item.get("item_name") for item in extracted_info
                        if item.get("item_name")
                    }
                    for item in new_items:
                        name = item.get("item_name")
                        if name and name not in existing_names:
                            extracted_info.append(item)
                            existing_names.add(name)
                        elif name:
                            # Already exists — prefer the newer result
                            for i, existing in enumerate(extracted_info):
                                if existing.get("item_name") == name:
                                    extracted_info[i] = item
                                    break

                # Per-skill checkpoint (P3)
                if settings.checkpointing_enabled:
                    self._checkpoint_manager.save(
                        session_id,
                        Checkpoint(
                            stage_name=skill_name,
                            stage_index=len(domain_results),
                            trace_id=trace_id,
                            input_data={"skill": skill_name, "message": message[:200]},
                            output_data={"success": skill_result.success},
                            created_at=__import__("datetime").datetime.now(),
                        ),
                    )

            if domain_skill_names and streamer:
                phase_domain.__exit__(None, None, None)

            # ── Fallback: inline RAG if the pipeline returned nothing ───────
            if requires_RAG and not extracted_info and streamer:
                phase_fallback = streamer.phase("RAG Fallback", emoji="🔄").__enter__()
                phase_fallback.step("Pipeline returned empty — falling back to LLM extraction...")
                extracted_info = await self._run_inline_rag(topic_details)
                phase_fallback.done(f"{len(extracted_info)} item(s) extracted via LLM")
                phase_fallback.__exit__(None, None, None)
            elif requires_RAG and not extracted_info:
                extracted_info = await self._run_inline_rag(topic_details)

            # ── Load UserPreferences (always) ─────────────────────────────
            user_preferences_context = ""
            if settings.use_order_flow_tracker:
                try:
                    if user_id in self._tracker_cache:
                        prefs = self._tracker_cache[user_id]._user_prefs
                    else:
                        prefs = UserPreferences.load(user_id)
                    if prefs:
                        user_preferences_context = prefs.to_prompt_context()
                except Exception as e:
                    logger.debug("Could not load user preferences: %s", e)
                    prefs = None

            # ── Create / reuse OrderFlowTracker (only for ordering) ─────────
            tracker = None
            if settings.use_order_flow_tracker:
                if requires_reconcilier:
                    ordering_segments = self._get_ordering_segments(
                        topic_details if isinstance(topic_details, list) else []
                    )
                    if ordering_segments:
                        is_new = user_id not in self._tracker_cache
                        if is_new:
                            if not prefs:
                                prefs = UserPreferences.load(user_id)
                            self._tracker_cache[user_id] = OrderFlowTracker(
                                user_id=user_id, user_prefs=prefs
                            )
                        tracker = self._tracker_cache[user_id]

            # ── Skill: response-build (always) ──────────────────────────────
            phase_response = streamer.phase("Response Generation", emoji="✍️").__enter__()
            phase_response.step("Building hybrid response from classification + RAG + order state...")

            response_build_skill = self._load_skill("response-build")
            with span("response-build"):
                response_result = await response_build_skill.execute(
                    {
                        "classification": classification_data,
                        "order_state": order,
                        "orchestrator_result": domain_results.get("order-flow", {}).value
                        if "order-flow" in domain_results
                        else {},
                        "message": message,
                        "summary_conversation": summary_conversation,
                        "extracted_info": extracted_info,
                        "tracker": tracker,
                        "brand_voice_path": settings.brand_voice_path,
                        "prompt_template_path": settings.response_generation_prompt_path,
                        "settings": settings,
                        "user_preferences_context": user_preferences_context,
                    },
                    trace_id=trace_id,
                )

            elapsed_time = time.time() - _pipeline_start
            response_text = FALLBACK_ERROR

            if response_result.success:
                response_text = response_result.value.get("response", FALLBACK_ERROR)
                phase_response.done(f"Generated {len(response_text)} chars")
            else:
                phase_response.result("Failed", str(response_result.error), is_error=True)
                phase_response.__exit__(None, None, None)
                return {
                    "response": FALLBACK_ERROR,
                    "classification": classification_data,
                    "extracted_info": extracted_info,
                    "pipeline_error": str(response_result.error),
                }
            phase_response.__exit__(None, None, None)

            _skills_msg = f"Skills: classify + {len(domain_skill_names)} domain + response-build"

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

        # ── Persist preferences after response ──────────────────────────
        if tracker and tracker._user_prefs:
            try:
                tracker._user_prefs.save()
            except Exception as save_err:
                logger.warning(f"Failed to save preferences: {save_err}")

        # ── Logging (framework) ─────────────────────────────────────────
        orchestrator_response = {}
        if "order-flow" in domain_results and domain_results["order-flow"].success:
            orchestrator_response = domain_results["order-flow"].value.get("orchestrator_response", {})

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
            "response_builder": self.response_builder,
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

    async def _run_inline_rag(
        self,
        topic_details: list,
    ) -> list:
        """Run LLM-based RAG extraction for each document referenced in topic_details.

        Groups segments by ``file_source``, reads each document, and uses
        the ``InformationLlmExtractor`` to extract relevant information.
        Returns a list of extracted items suitable for ``extracted_info``.
        """
        from src.core.classifier.intent import DocumentSource

        # Group segments by file_source, skipping no-file / empty
        groups: dict = {}
        for td in topic_details:
            fs = td.get("file_source", "") if isinstance(td, dict) else getattr(td, "file_source", "")
            if fs and fs not in ("no-file", DocumentSource.NONE, ""):
                groups.setdefault(fs, []).append(td)

        if not groups:
            return []

        if streamer := getattr(self, "_streamer", None):
            pass  # caller's streamer is passed externally — see _run_orchestration_loop

        results = []
        for doc_name, segments in groups.items():
            doc_path = f"{settings.documents_path}/{doc_name}"
            try:
                with open(doc_path, 'r', encoding='utf-8') as f:
                    content = f.read()
            except (FileNotFoundError, IOError):
                logger.warning("RAG doc not found: %s", doc_path)
                continue

            # Use InformationLlmExtractor.extract() per segment
            for segment in segments:
                seg_text = segment.get("segment", "") if isinstance(segment, dict) else getattr(segment, "segment", "")
                if not seg_text:
                    continue
                try:
                    extracted = await self.extractor.extract(seg_text, content)
                    if extracted and "No se encuentra" not in extracted:
                        results.append({
                            "item_name": extracted[:500],
                            "source": doc_name,
                            "score": 1.0,
                            "match_type": "extracted",
                        })
                except Exception as e:
                    logger.warning("RAG extract failed for %s: %s", doc_name, e)

        return results

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
                    guard_tracker = None
                    if settings.use_order_flow_tracker and user_id in self._tracker_cache:
                        guard_tracker = self._tracker_cache[user_id]

                    llm_guard_result = await self._stage_llm_guard(
                        message,
                        session_ctx.summary_conversation,
                        session_ctx.summary_order,
                        tracker=guard_tracker,
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

    @staticmethod
    def _is_full_menu_request(topic_details: list) -> bool:
        """Detect if the user is asking for the full menu (vs. a specific query).

        Checks topic_details for consulting segments with ``topic: menu``
        and a segment text or focus that indicates a generic "show me the
        whole menu" request, rather than a specific item/ingredient query.

        Returns:
            True if the request is for the full menu.
        """
        # Patterns that indicate a generic full-menu request
        full_menu_patterns = [
            "la carta", "el menú", "menú completo", "todo el menú",
            "qué hay", "qué tienen", "qué ofrecen",
            "dame el menú", "regalan la carta", "quiero ver el menú",
            "muéstrame el menú", "cuál es el menú",
        ]
        # Focus phrases from the classifier
        focus_patterns = [
            "solicitar el menú", "menú del restaurante",
            "consultar el menú completo", "ver el menú",
        ]

        for td in topic_details:
            seg = (
                td.get("segment", "")
                if isinstance(td, dict)
                else getattr(td, "segment", "")
            )
            topic = (
                td.get("topic", "")
                if isinstance(td, dict)
                else getattr(td, "topic", "")
            )
            if topic != "menu":
                continue

            seg_lower = seg.lower().strip()
            if any(p in seg_lower for p in full_menu_patterns):
                return True

            # Also check the focus field from the classifier
            focus = (
                td.get("focus", "")
                if isinstance(td, dict)
                else getattr(td, "focus", "")
            )
            focus_lower = focus.lower()
            if any(p in focus_lower for p in focus_patterns):
                return True

        return False

    @staticmethod
    def _get_ordering_segments(topic_details: list) -> list:
        """Filter segments relevant to ordering flow.

        Returns only segments whose query_type indicates an ordering-related
        intent (ORDERING, CONFIRMATION, CANCELLATION, CLARIFICATION).
        Handles both Detail objects (Pydantic) and dicts (from model_dump).
        """
        ordering_types = {
            QueryType.ORDERING, QueryType.CONFIRMATION,
            QueryType.CANCELLATION, QueryType.CLARIFICATION,
        }

        def _get_type(d):
            if hasattr(d, "query_type"):
                return d.query_type
            return d.get("query_type")

        return [d for d in topic_details if _get_type(d) in ordering_types]


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
