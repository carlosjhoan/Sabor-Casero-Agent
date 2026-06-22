"""
Planner — LLM-driven tool-calling loop for skill orchestration.

The Planner replaces the fixed sequential pipeline with a flexible
LLM-driven loop where the model decides which tools (skills) to call
and in what order, then calls ``respond`` to produce the final answer.

Usage::

    planner = Planner(llm_client, orchestrator, streamer, settings)
    context = PlannerContext(
        summary_conversation="...",
        summary_order="...",
        ...
    )
    response = await planner.run(message, context)
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from src.engine.skill_registry import SkillRegistry
from src.engine.skill_tools import SkillToolAdapter
from src.utils.pipeline_streamer import PipelineStreamer

logger = logging.getLogger("Planner")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_TOOL_CALLS = 5

FALLBACK_ERROR = (
    "Lo siento, no pude generar una respuesta. Por favor intenta de nuevo."
)

# ---------------------------------------------------------------------------
# PlannerState
# ---------------------------------------------------------------------------


class PlannerState(Enum):
    """State machine for the planner loop."""

    THINKING = "thinking"
    EXECUTING = "executing"
    REFLECTING = "reflecting"
    TERMINATED = "terminated"


# ---------------------------------------------------------------------------
# PlannerContext
# ---------------------------------------------------------------------------


@dataclass
class PlannerContext:
    """Conversation context injected into the planner's system prompt.

    Attributes
    ----------
    summary_conversation : str
        Summary of previous conversation turns.
    summary_order : str
        Current order state as readable text.
    user_preferences_context : str
        Known preferences for the current user.
    user_id : str
        Unique identifier for the current user.
    session_id : str
        Current session identifier.
    candidates : list
        Known menu item names (for candidate-based skills).
    topic_details : list
        Classification topic details — passed to domain skills.
    """

    summary_conversation: str = ""
    summary_order: str = ""
    user_preferences_context: str = ""
    user_id: str = ""
    session_id: str = ""
    candidates: list = field(default_factory=list)
    topic_details: list = field(default_factory=list)
    order_checklist_status: str = ""
    memory_entities: str = ""


# ---------------------------------------------------------------------------
# Built-in respond tool definition
# ---------------------------------------------------------------------------

RESPOND_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "respond",
        "description": (
            "Provide the final response to the user and end the "
            "conversation turn."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "response_text": {
                    "type": "string",
                    "description": (
                        "The final response in Spanish, warm and helpful"
                    ),
                },
            },
            "required": ["response_text"],
        },
    },
}


# ---------------------------------------------------------------------------
# Planner
# ---------------------------------------------------------------------------


class Planner:
    """LLM-driven tool-calling loop for skill orchestration.

    Parameters
    ----------
    llm_client : LiteLLMClient
        The LLM client to use for chat completion with tool support.
    skill_orchestrator : SkillOrchestrator
        Orchestrator that loads and manages skills.
    streamer : PipelineStreamer or None
        Optional streamer for phase-level progress output.
    settings : Settings or None
        Application settings (used to read model config).
    registry : SkillRegistry or None
        Skill registry (falls back to the orchestrator's registry).
    trace_id : str
        Current trace identifier for observability.
    """

    def __init__(
        self,
        llm_client,
        skill_orchestrator,
        streamer,
        settings,
        registry=None,
        trace_id: str = "",
        extractor=None,
        skill_context: dict | None = None,
    ):
        self._llm = llm_client
        self._orchestrator = skill_orchestrator
        self._streamer = streamer
        self._settings = settings
        self._registry = registry or getattr(skill_orchestrator, "registry", None)
        self._trace_id = trace_id
        self._extractor = extractor
        self._skill_context = skill_context or {}

        # Internal state
        self._tool_call_count: int = 0
        self._state: PlannerState = PlannerState.THINKING
        self._messages: list[dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(
        self,
        message: str,
        context: PlannerContext,
        previous_messages: list | None = None,
    ) -> str:
        """Execute the planning loop for a single user message.

        Args:
            message: The user's current message.
            context: A ``PlannerContext`` with conversation and order
                     state.
            previous_messages: Messages from the previous turn to prepend
                               (assistant + tool blocks, excluding system
                               prompt and user message).

        Returns:
            Final response text (in Spanish).
        """
        self._tool_call_count = 0
        self._state = PlannerState.THINKING

        # Build system prompt with injected context
        system_prompt = self._build_system_prompt(context)

        # Initialise the message list, preserving history from previous turn
        self._messages = [{"role": "system", "content": system_prompt}]
        if previous_messages:
            # Limit to ~12 messages (~1-2 turns of tool activity)
            if len(previous_messages) > 12:
                previous_messages = previous_messages[-12:]
            self._messages.extend(previous_messages)
        self._messages.append({"role": "user", "content": message})

        # Gather tool definitions (registry skills + built-in respond)
        registry_tools = SkillToolAdapter.list_tools(self._registry)
        all_tools: list[dict] = registry_tools + [RESPOND_TOOL]

        # Build the orchestration context dict for SkillToolAdapter
        orchestration_context = self._build_orchestration_context(context)

        try:
            return await self._tool_loop(all_tools, orchestration_context)
        except Exception as exc:
            logger.exception("Planner crashed: %s", exc)
            if self._streamer:
                with self._streamer.phase("Planning") as p:
                    p.result("Crashed", f"{type(exc).__name__}: {exc}", is_error=True)
            return FALLBACK_ERROR

    # ------------------------------------------------------------------
    # Core tool-calling loop
    # ------------------------------------------------------------------

    async def _tool_loop(
        self,
        tools: list[dict],
        orchestration_context: dict[str, Any],
    ) -> str:
        """Run the LLM tool-calling loop until ``respond`` or cap."""
        last_assistant_text = ""

        while self._tool_call_count < MAX_TOOL_CALLS:
            self._state = PlannerState.THINKING

            # ── Phase: Planning ──────────────────────────────────────
            if self._streamer:
                with self._streamer.phase("Planning") as p:
                    p.step("Thinking about next step...")

            # ── LLM call ─────────────────────────────────────────────
            try:
                # Determine the model to use
                model = getattr(self._settings, "llm_model_response", None) or "deepseek/deepseek-chat"

                async with asyncio.timeout(10):
                    response = await self._llm.chat_completion(
                        messages=self._messages,
                        model=model,
                        tools=tools,
                        temperature=0.3,
                    )
            except asyncio.TimeoutError:
                logger.warning("LLM call timed out after 10s")
                if self._streamer:
                    with self._streamer.phase("Planning") as p:
                        p.result("Timeout", "LLM did not respond in time", is_error=True)
                continue  # retry
            except Exception as exc:
                logger.warning("LLM call failed: %s", exc)
                if self._streamer:
                    with self._streamer.phase("Planning") as p:
                        p.result("Failed", str(exc), is_error=True)
                continue  # retry

            # ── Parse LLM response ───────────────────────────────────

            # Tool-call response (dict from LiteLLMClient)
            if isinstance(response, dict) and response.get("finish_reason") == "tool_calls":
                tool_calls = response.get("tool_calls", [])
                assistant_msg = response.get("assistant_message", "") or ""
                reasoning = response.get("reasoning_content", "") or ""

                if assistant_msg:
                    last_assistant_text = assistant_msg

                # Show LLM reasoning in the Planning phase
                if reasoning and self._streamer:
                    with self._streamer.phase("Planning") as p:
                        p.info("Thinking", reasoning)
                elif assistant_msg and self._streamer:
                    with self._streamer.phase("Planning") as p:
                        p.info("Thinking", assistant_msg)

                if not tool_calls:
                    # No tool calls despite tool_calls finish reason —
                    # treat as fallback text
                    if assistant_msg:
                        self._messages.append({
                            "role": "assistant",
                            "content": assistant_msg,
                        })
                        return assistant_msg
                    break

                # ── Build a SINGLE assistant message for ALL tool calls
                #     from this turn (OpenAI-compatible format).
                assistant_entry: dict[str, Any] = {
                    "role": "assistant",
                    "content": assistant_msg if assistant_msg else None,
                    "tool_calls": [
                        {
                            "id": tc.get("id", ""),
                            "type": "function",
                            "function": {
                                "name": tc.get("name", ""),
                                "arguments": json.dumps(
                                    tc.get("arguments", {}),
                                    ensure_ascii=False,
                                ),
                            },
                        }
                        for tc in tool_calls
                    ],
                }
                self._messages.append(assistant_entry)

                # ── Execute each tool call ────────────────────────
                for tc in tool_calls:
                    if self._tool_call_count >= MAX_TOOL_CALLS:
                        break

                    tool_name = tc.get("name", "")
                    tool_args = tc.get("arguments", {})
                    tool_id = tc.get("id", "")

                    # Built-in: respond → terminate
                    if tool_name == "respond":
                        self._state = PlannerState.TERMINATED
                        response_text = tool_args.get("response_text", "")
                        if not response_text:
                            response_text = last_assistant_text or FALLBACK_ERROR
                        if self._streamer:
                            with self._streamer.phase("Response") as p:
                                p.done("Final response ready")
                        return response_text

                    # Increment counter BEFORE execution
                    self._state = PlannerState.EXECUTING
                    self._tool_call_count += 1

                    # Execute skill via SkillToolAdapter
                    tool_result = await SkillToolAdapter.execute_tool(
                        tool_name, tool_args, orchestration_context,
                    )

                    self._state = PlannerState.REFLECTING

                    # Append tool result to conversation
                    if tool_result.get("success"):
                        result_text = json.dumps(
                            tool_result.get("result", {}),
                            ensure_ascii=False,
                            default=str,
                        )
                        self._messages.append({
                            "role": "tool",
                            "tool_call_id": tool_id,
                            "content": result_text,
                        })
                    else:
                        error_text = tool_result.get("error", "Unknown error")
                        self._messages.append({
                            "role": "tool",
                            "tool_call_id": tool_id,
                            "content": f"Error: {error_text}",
                        })

                    # ── Phase: Reflection ─────────────────────────
                    if self._streamer:
                        with self._streamer.phase("Reflection") as p:
                            if tool_result.get("success"):
                                result_preview = json.dumps(
                                    tool_result.get("result", {}),
                                    ensure_ascii=False,
                                    default=str,
                                )
                                p.done(f"{tool_name} → {result_preview}")
                            else:
                                p.result(
                                    "Failed",
                                    tool_result.get("error", "Unknown"),
                                    is_error=True,
                                )

                # Continue loop — the assistant + tool messages are now
                # in self._messages so the next LLM call sees them.
                continue

            # Plain-text response (no tool calls)
            if isinstance(response, str) and response.strip():
                last_assistant_text = response
                self._messages.append({
                    "role": "assistant",
                    "content": response,
                })
                break

            # Empty or unexpected response format
            logger.warning(
                "Unexpected LLM response format: %s | content=%r",
                type(response).__name__,
                response,
            )
            break

        # ── Loop exhausted without respond ─────────────────────────────
        self._state = PlannerState.TERMINATED

        if self._tool_call_count >= MAX_TOOL_CALLS:
            logger.warning("Planner hard cap (%d tool calls) reached", MAX_TOOL_CALLS)
            if self._streamer:
                with self._streamer.phase("Response") as p:
                    p.result("Capped", "Maximum tool calls reached", is_error=True)
            return FALLBACK_ERROR

        # Fallback: return the last assistant text we have
        if last_assistant_text:
            if self._streamer:
                with self._streamer.phase("Response") as p:
                    p.done("Using fallback response")
            return last_assistant_text

        return FALLBACK_ERROR

    # ------------------------------------------------------------------
    # Prompt building
    # ------------------------------------------------------------------

    def _build_system_prompt(self, context: PlannerContext) -> str:
        """Read the planner prompt template and inject context."""
        prompt_path = getattr(self._settings, "planner_prompt_path", "prompts/planner/system_prompt.txt")
        try:
            with open(prompt_path, "r", encoding="utf-8") as f:
                template = f.read()
        except FileNotFoundError:
            logger.warning("Planner prompt not found at %s — using fallback", prompt_path)
            template = self._fallback_prompt_template()

        # Build readable skill descriptions from the registry
        skill_descriptions = self._format_skill_descriptions()

        # Inject all placeholders
        prompt = template.replace("{skill_descriptions}", skill_descriptions)
        prompt = prompt.replace(
            "{conversation_history}",
            context.summary_conversation or "No hay historial de conversación.",
        )
        prompt = prompt.replace(
            "{user_preferences}",
            context.user_preferences_context or "No hay preferencias registradas.",
        )
        prompt = prompt.replace(
            "{order_state}",
            context.summary_order or "El cliente no ha realizado pedido.",
        )
        prompt = prompt.replace(
            "{order_checklist_status}",
            context.order_checklist_status or "No hay pedido activo.",
        )
        prompt = prompt.replace(
            "{memory_entities}",
            context.memory_entities or "",
        )

        return prompt

    def _format_skill_descriptions(self) -> str:
        """Format all registered skills as a readable list for the LLM."""
        lines: list[str] = []
        for meta in self._registry.list_skills():
            desc = meta.trigger or "(sin descripción)"
            lines.append(f"- **{meta.display}** (`{meta.name}`): {desc}")
        return "\n".join(lines)

    @staticmethod
    def _fallback_prompt_template() -> str:
        """Return a minimal fallback prompt when the template file is
        missing."""
        return (
            "Eres Luz Stella, la amable asistente virtual del restaurante "
            "Sabor Casero.\n\n"
            "## Herramientas Disponibles\n\n"
            "{skill_descriptions}\n\n"
            "## Contexto de Conversación\n\n"
            "**Historial de conversación:**\n{conversation_history}\n\n"
            "**Preferencias del usuario:**\n{user_preferences}\n\n"
            "**Estado del pedido actual:**\n{order_state}\n\n"
            "Debes usar las herramientas disponibles para ayudar al "
            "cliente y finalizar llamando a `respond` con tu respuesta final."
        )

    # ------------------------------------------------------------------
    # Orchestration context for SkillToolAdapter
    # ------------------------------------------------------------------

    def _build_orchestration_context(
        self,
        context: PlannerContext,
    ) -> dict[str, Any]:
        """Build the context dict expected by
        ``SkillToolAdapter.execute_tool()``.

        Includes all dependencies that skills expect in their ``load()``
        method — the same fields that ``assistant._load_skill()`` provides.
        Merges with ``self._skill_context`` (passed from the assistant) so
        that skills like ``order-flow`` and ``response-build`` have access
        to ``order_orchestrator``, ``response_builder``, etc.
        """
        extractor = self._extractor
        base = {
            "llm_client": self._llm,
            "skill_orchestrator": self._orchestrator,
            "streamer": self._streamer,
            "settings": self._settings,
            "session_id": context.session_id,
            "summary_conversation": context.summary_conversation,
            "summary_order": context.summary_order,
            "user_preferences_context": context.user_preferences_context,
            "candidates": context.candidates,
            "trace_id": self._trace_id,
            # Skill dependencies (mirrors assistant._load_skill context)
            "owl_client": getattr(extractor, "_owl_client", None) if extractor else None,
            "owl_signal": getattr(extractor, "_owl_signal", None) if extractor else None,
            "retriever": extractor,
            "bm25_retriever": getattr(extractor, "_bm25", None) if extractor else None,
            "entity_retriever": getattr(extractor, "_entity", None) if extractor else None,
            "rrf_fuser": getattr(extractor, "_rrf_fuser", None) if extractor else None,
            "cross_encoder": getattr(extractor, "_cross_encoder", None) if extractor else None,
            "ontology_gate": getattr(extractor, "_ontology_gate", None) if extractor else None,
            "summary_index": self._skill_context.get("summary_index"),
        }
        # Merge with assistant-level skill context (order_orchestrator,
        # response_builder, classifier, memory_hub, summarizer, etc.)
        base.update(self._skill_context)
        return base

    # ------------------------------------------------------------------
    # Accessors (for orchestrator inspection)
    # ------------------------------------------------------------------

    @property
    def tool_call_count(self) -> int:
        """Number of tool calls made during the last ``run()``."""
        return self._tool_call_count

    @property
    def state(self) -> PlannerState:
        """Current state of the planner."""
        return self._state
