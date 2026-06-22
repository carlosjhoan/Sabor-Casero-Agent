"""
SkillToolAdapter — bridges skills as callable tools for the LLM Planner.

Converts the ``SkillRegistry`` index into OpenAI-compatible tool definitions
and provides an async dispatcher that loads a skill, injects orchestration
context, executes it, and returns a serializable result dict.

Also provides built-in synthetic tools (``respond``, ``get-full-menu``) that
are not backed by a skill but are available to the Planner.

Usage::

    tools = SkillToolAdapter.list_tools(registry)
    result = await SkillToolAdapter.execute_tool("menu-query", {"query": "tacos"}, context)
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


# Built-in synthetic tool: full menu (not backed by a skill)
_FULL_MENU_TOOL = {
    "type": "function",
    "function": {
        "name": "get-full-menu",
        "description": (
            "Returns the COMPLETE restaurant menu with ALL items organized "
            "by section (Sopa, Principio, Acompañamientos, Proteínas), "
            "including prices and options. "
            "Use this INSTEAD of menu-query when the user asks for "
            "'la carta', 'el menú', 'qué tienen', 'qué hay para hoy', "
            "'qué ofrecen', 'menú completo', or similar GENERAL menu requests."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
}

# --- Synthetic order tools (granular-order-tools) ---
# These replace the order-flow skill when use_llm_planner=True.
# Each maps to a CRUD method on OrderOrchestrator.

_ADD_ITEM_TOOL = {
    "type": "function",
    "function": {
        "name": "add-item",
        "description": "Add an item to the order. Creates a new order if none exists for this session. "
                       "At least one of 'protein' or 'principle' must be provided — items can be created "
                       "partially and completed later via update-item.",
        "parameters": {
            "type": "object",
            "properties": {
                "protein": {"type": "string", "description": "Main dish / protein"},
                "quantity": {"type": "integer", "description": "Quantity (default 1)"},
                "size": {"type": "string", "enum": ["corriente", "mini"], "description": "Portion size"},
                "principle": {"type": "string", "description": "Side / principle"},
                "requirements": {"type": "array", "items": {"type": "string"}, "description": "Special requests"},
                "unit_price": {"type": "number", "description": "Unit price"},
            },
            "required": [],
        },
    },
}

_REMOVE_ITEM_TOOL = {
    "type": "function",
    "function": {
        "name": "remove-item",
        "description": "Remove an item from the current order by item_id.",
        "parameters": {
            "type": "object",
            "properties": {
                "item_id": {"type": "string", "description": "ID of the item to remove"},
            },
            "required": ["item_id"],
        },
    },
}

_UPDATE_ITEM_TOOL = {
    "type": "function",
    "function": {
        "name": "update-item",
        "description": "Update an existing item in the current order.",
        "parameters": {
            "type": "object",
            "properties": {
                "item_id": {"type": "string", "description": "ID of the item to update"},
                "quantity": {"type": "integer"},
                "protein": {"type": "string"},
                "size": {"type": "string", "enum": ["corriente", "mini"]},
                "principle": {"type": "string"},
                "requirements": {"type": "array", "items": {"type": "string"}},
                "unit_price": {"type": "number"},
            },
            "required": ["item_id"],
        },
    },
}

_GET_ORDER_TOOL = {
    "type": "function",
    "function": {
        "name": "get-order",
        "description": "Get the current order summary (items, totals, status).",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
}

_CONFIRM_ORDER_TOOL = {
    "type": "function",
    "function": {
        "name": "confirm-order",
        "description": "Confirm the current order (sets status to confirmed).",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
}

_CANCEL_ORDER_TOOL = {
    "type": "function",
    "function": {
        "name": "cancel-order",
        "description": "Cancel the current order (sets status to cancelled).",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
}

_UPDATE_ORDER_TOOL = {
    "type": "function",
    "function": {
        "name": "update-order",
        "description": "Update order-level metadata (customer name, service type, address, "
                       "scheduled time, payment method, observations, con_todo). "
                       "Use this for fields at the ORDER level, not item level. "
                       "Item-level fields use update-item.",
        "parameters": {
            "type": "object",
            "properties": {
                "customer_name": {"type": "string", "description": "Customer's full name"},
                "con_todo": {"type": "string", "description": "Confirmation of full accompaniment ('sí' or specific modifications)"},
                "service_type": {"type": "string", "enum": ["delivery", "pickup"], "description": "Delivery or pickup"},
                "address": {"type": "string", "description": "Delivery address (only for delivery)"},
                "scheduled_time": {"type": "string", "description": "Pickup time (only for pickup), e.g. '14:30'"},
                "payment_method": {"type": "string", "description": "Payment method (efectivo, nequi, etc.)"},
                "observations": {"type": "array", "items": {"type": "string"}, "description": "Order-level notes or modifications"},
            },
            "required": [],
        },
    },
}

_SET_FIELD_NOTE_TOOL = {
    "type": "function",
    "function": {
        "name": "set-field-note",
        "description": "Registra que preguntaste por un campo pero el usuario no respondió. "
                       "Úsala cuando preguntes por un campo (protein, size, principle, etc.) "
                       "y el usuario se desvíe a otro tema. La nota queda visible en el checklist "
                       "para que no preguntes lo mismo dos veces.",
        "parameters": {
            "type": "object",
            "properties": {
                "field": {
                    "type": "string",
                    "enum": ["protein", "size", "principle", "con_todo", "customer_name",
                             "service_type", "address", "scheduled_time", "payment_method",
                             "observations"],
                    "description": "Nombre del campo que preguntaste y el usuario no respondió"
                },
                "note": {
                    "type": "string",
                    "description": "Qué hizo el usuario en vez de responder (ej: 'preguntó por precios', 'pidió cambiar de plato')"
                },
            },
            "required": ["field", "note"],
        },
    },
}

# --- Synthetic doc-query tool ---
# Exposes the SummaryIndex + lazy RAG pipeline to the Planner.
_DOC_QUERY_TOOL = {
    "type": "function",
    "function": {
        "name": "doc-query",
        "description": (
            "Search restaurant documents for specific information using "
            "semantic search across ALL documents (service info, waiter guide, "
            "about us, policies, etc.). "
            "Use this when business-info doesn't cover what the user needs, "
            "or when you need specific details from ANY document. "
            "Optionally narrow by topic for faster results."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query — what information you need",
                },
                "topic": {
                    "type": "string",
                    "enum": [
                        "hours", "delivery", "payment", "complaint",
                        "general", "about", "waiter", "ingredients",
                        "special_offers", "menu",
                    ],
                    "description": "Optional: narrow search to a specific topic",
                },
            },
            "required": ["query"],
        },
    },
}

# All synthetic order tools in a list for iteration
_SYNTHETIC_ORDER_TOOLS = [
    _ADD_ITEM_TOOL,
    _REMOVE_ITEM_TOOL,
    _UPDATE_ITEM_TOOL,
    _GET_ORDER_TOOL,
    _CONFIRM_ORDER_TOOL,
    _CANCEL_ORDER_TOOL,
    _UPDATE_ORDER_TOOL,
]

# Mapping from tool name to constant for dispatch
_SYNTHETIC_ORDER_TOOL_MAP = {
    t["function"]["name"]: t for t in _SYNTHETIC_ORDER_TOOLS
}


class SkillToolAdapter:
    """Converts skills to/from LLM-callable tools."""

    # ------------------------------------------------------------------
    # Tool definitions
    # ------------------------------------------------------------------

    # Skills that the system handles automatically — the Planner should NOT
    # call them directly. memory-store, summarize, and response-build run
    # automatically in post-processing.
    _AUTOMATIC_SKILLS = {"memory-store", "summarize", "response-build", "order-flow"}

    # Skills that depend on OWL infrastructure (OwlClient, OwlSignal).
    # When USE_OWL=False, these are removed from the Planner's tool list.
    # Note: rag-retrieve uses the multi-signal pipeline (dense + BM25 +
    # entity + OWL partial). Without OWL it falls back to dense + BM25 +
    # entity, which work with pure ChromaDB/vector search.
    _OWL_DEPENDENT_SKILLS = {"menu-query"}

    @staticmethod
    def list_tools(registry) -> list[dict]:
        """Build OpenAI-compatible tool definitions from a SkillRegistry.

        Includes decision-making skills (classify, menu-query, rag-retrieve,
        order-flow) plus built-in synthetic tools (``get-full-menu``).
        Automatic system skills (memory-store, summarize, response-build)
        are excluded — they run outside the Planner loop.

        When ``USE_OWL=False`` (from settings), OWL-dependent skills
        (menu-query, rag-retrieve, get-full-menu) are also excluded.

        Args:
            registry: A ``SkillRegistry`` instance (already discovered).

        Returns:
            List of tool definition dicts in OpenAI ``"type": "function"`` format.
        """
        all_tools = registry.get_tool_definitions()

        # Start with skills that aren't automatic
        skill_tools = [
            t for t in all_tools
            if t.get("function", {}).get("name") not in SkillToolAdapter._AUTOMATIC_SKILLS
        ]

        # Filter OWL-dependent skills when OWL is disabled
        try:
            from src.config.environment import settings
            owl_enabled = getattr(settings, "use_owl", True)
            if not owl_enabled:
                skill_tools = [
                    t for t in skill_tools
                    if t.get("function", {}).get("name") not in SkillToolAdapter._OWL_DEPENDENT_SKILLS
                ]
        except Exception:
            pass  # settings not available — keep OWL skills

        # Always add get-full-menu — has fallback to read menu.md directly
        # when OwlClient is not available (USE_OWL=false).
        skill_tools.append(_FULL_MENU_TOOL)

        # Always add business-info — reads about_us.txt and service_info.txt
        # directly from disk, no OWL dependency.
        skill_tools.append(_BUSINESS_INFO_TOOL)

        # Always add doc-query — uses SummaryIndex for routing + lazy ChromaDB RAG.
        # No dependencies on OWL or menu structure.
        skill_tools.append(_DOC_QUERY_TOOL)

        # Add synthetic order tools (granular-order-tools) — these replace
        # the order-flow skill when use_llm_planner=True.
        skill_tools.extend(_SYNTHETIC_ORDER_TOOLS)

        return skill_tools

    # ------------------------------------------------------------------
    # Tool execution
    # ------------------------------------------------------------------

    @classmethod
    async def execute_tool(
        cls,
        name: str,
        args: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute a skill by name with the given arguments and orchestration context.

        Loads the skill via ``SkillOrchestrator.load_skill()``, injects relevant
        context fields into the input data, and calls ``skill.execute()``.

        Also handles built-in synthetic tools (``get-full-menu``) that are not
        backed by a skill module.

        Args:
            name: Registered skill name (e.g. ``"classify"``, ``"menu-query"``).
            args: Input arguments for the skill (from the LLM tool call).
            context: Orchestration context dict with keys:
                ``llm_client``, ``skill_orchestrator``, ``streamer``, ``settings``,
                ``summary_conversation``, ``summary_order``, ``user_preferences_context``,
                ``candidates``, ``trace_id``.

        Returns:
            A JSON-serializable dict:
            ``{"success": True, "result": {...}}`` on success, or
            ``{"success": False, "error": "..."}`` on failure.
        """
        try:
            # ── Built-in: get-full-menu (not backed by a skill) ──────────
            if name == "get-full-menu":
                owl_client = context.get("owl_client")
                if owl_client and hasattr(owl_client, "get_full_menu"):
                    menu_text = owl_client.get_full_menu()
                    return {"success": True, "result": {"menu": menu_text}}
                # Fallback when OWL is disabled: read menu.md directly
                try:
                    from src.config.environment import settings
                    menu_path = getattr(settings, "documents_path", "data/documents")
                    import os
                    md_path = os.path.join(menu_path, "menu.md")
                    if os.path.exists(md_path):
                        with open(md_path, "r", encoding="utf-8") as f:
                            menu_text = f.read()
                        return {"success": True, "result": {"menu": menu_text}}
                except Exception as e:
                    logger.debug("Full menu fallback failed: %s", e)
                return {"success": False, "error": "Full menu not available"}

            # ── Built-in: doc-query (SummaryIndex + lazy ChromaDB RAG) ──
            if name == "doc-query":
                return cls._execute_doc_query(args, context)

            # ── Built-in: business-info (not backed by a skill) ──────────
            if name == "business-info":
                try:
                    from src.config.environment import settings
                    doc_path = getattr(settings, "documents_path", "data/documents") or "data/documents"
                    import os
                    result = {}
                    for fname in ("about_us.txt", "service_info.txt"):
                        fpath = os.path.join(doc_path, fname)
                        if os.path.exists(fpath):
                            with open(fpath, "r", encoding="utf-8") as f:
                                result[fname.replace(".txt", "")] = f.read()
                    if result:
                        return {"success": True, "result": result}
                except Exception as e:
                    logger.debug("Business info fallback failed: %s", e)
                return {"success": False, "error": "Business information not available"}

            # ── Synthetic order tools ──────────────────────────────
            if name in _SYNTHETIC_ORDER_TOOL_MAP:
                order_orchestrator = context.get("order_orchestrator")
                session_id = context.get("session_id")
                if not order_orchestrator:
                    return {"success": False, "error": "order_orchestrator not available in context"}
                if not session_id:
                    return {"success": False, "error": "session_id not available in context"}

                if name == "add-item":
                    result = await order_orchestrator.add_item(session_id, args)
                elif name == "remove-item":
                    result = await order_orchestrator.remove_item(session_id, args.get("item_id", ""))
                elif name == "update-item":
                    item_id = args.get("item_id", "")
                    changes = {k: v for k, v in args.items() if k != "item_id"}
                    result = await order_orchestrator.update_item(session_id, item_id, changes)
                elif name == "get-order":
                    result = await order_orchestrator.get_order(session_id)
                elif name == "confirm-order":
                    result = await order_orchestrator.confirm_order(session_id)
                elif name == "cancel-order":
                    result = await order_orchestrator.cancel_order(session_id)
                elif name == "update-order":
                    result = await order_orchestrator.update_order(session_id, args)
                else:
                    return {"success": False, "error": f"Unknown synthetic order tool: {name}"}

                # CRUD returns {success, data, error} — normalize to {success, result, error}
                if result.get("success"):
                    return {"success": True, "result": result.get("data")}
                return {"success": False, "error": result.get("error")}

            orchestrator = context.get("skill_orchestrator")

            # Build input data: merge caller-provided args with auto-injected
            # context fields that the skill's Contract may need.
            input_data = dict(args)

            # Auto-inject context based on skill Contract needs
            cls._inject_context(input_data, name, context)

            # Load and execute the skill
            skill = orchestrator.load_skill(name, context=context)
            result = await skill.execute(
                input_data,
                trace_id=context.get("trace_id", ""),
            )

            if result.success:
                # SkillResult is a Pydantic BaseModel — serialize its value
                return {"success": True, "result": result.value}
            else:
                error_msg = str(result.error) if result.error else "Unknown skill error"
                return {"success": False, "error": error_msg}

        except Exception as exc:
            return {"success": False, "error": f"{type(exc).__name__}: {exc}"}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @classmethod
    async def _execute_doc_query(
        cls,
        args: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """doc-query execution: SummaryIndex routing → lazy ChromaDB RAG.

        Args:
            args: {"query": str, "topic"?: str} from the LLM tool call.
            context: Full orchestration context (needs 'summary_index').

        Returns:
            {"success": True, "result": {"content": ..., "source": ...}}
            o {"success": False, "error": "..."}
        """
        try:
            query = args.get("query", "").strip()
            topic = args.get("topic", "").strip()
            if not query:
                return {"success": False, "error": "query is required"}

            # 1. Get SummaryIndex from orchestration context
            summary_index = context.get("summary_index")
            if not summary_index:
                return {"success": False, "error": "summary_index not available"}

            # 2. Route query to relevant document(s)
            # If topic given, incorporate it for better routing
            search_query = f"{topic}: {query}" if topic else query
            relevant_docs = summary_index.query(search_query, top_k=2)
            if not relevant_docs:
                # Fallback: no summary matched — try direct topic→doc mapping
                if topic:
                    mapping = {
                        "hours": "service_info.txt", "delivery": "service_info.txt",
                        "payment": "service_info.txt", "complaint": "service_info.txt",
                        "general": "service_info.txt", "about": "about_us.txt",
                        "waiter": "waiter_guide.txt", "menu": "menu.md",
                        "ingredients": "menu.md", "special_offers": "menu.md",
                    }
                    doc = mapping.get(topic)
                    if doc and doc in summary_index.list_documents():
                        relevant_docs = [doc]

            if not relevant_docs:
                return {"success": True, "result": {
                    "content": "", "source": "",
                    "note": "No relevant documents found for this query.",
                }}

            # 3. Get retriever for ChromaDB queries
            retriever = context.get("retriever")
            if not retriever:
                return {"success": False, "error": "retriever not available"}

            # Extract HybridRetriever (might be wrapped in CompositeRetriever)
            hybrid = getattr(retriever, "_fallback", retriever)
            if not hasattr(hybrid, "query_document"):
                return {"success": False, "error": "retriever does not support query_document"}

            # 4. Lazy RAG: query each relevant document
            content_parts = []
            sources = []
            for doc in relevant_docs:
                # Lazy: ensure the doc has a summary (it should if it's in the index)
                result = hybrid.query_document(query, doc_name=doc)
                if result:
                    content_parts.append(f"--- {doc} ---\n{result}")
                    sources.append(doc)

            if not content_parts:
                # Fallback: return raw summary as context
                for doc in relevant_docs:
                    summary = summary_index.get_summary(doc)
                    if summary:
                        content_parts.append(f"--- {doc} ---\n{summary}")
                        sources.append(doc)

            return {"success": True, "result": {
                "content": "\n\n".join(content_parts) if content_parts else "",
                "source": ", ".join(sources) if sources else "",
            }}

        except Exception as exc:
            logger.exception("doc-query failed")
            return {"success": False, "error": f"{type(exc).__name__}: {exc}"}

    @classmethod
    def _inject_context(
        cls,
        input_data: dict[str, Any],
        skill_name: str,
        context: dict[str, Any],
    ) -> None:
        """Auto-inject orchestration context fields into input_data.

        Args:
            input_data: Mutable dict of arguments (modified in place).
            skill_name: Name of the skill being executed.
            context: Full orchestration context dict.
        """
        # classify uses conversation/order summaries + user preferences
        if skill_name == "classify":
            if "summary_conversation" not in input_data:
                input_data["summary_conversation"] = context.get("summary_conversation", "")
            if "summary_order" not in input_data:
                input_data["summary_order"] = context.get("summary_order", "")
            if "user_preferences_context" not in input_data:
                input_data["user_preferences_context"] = context.get("user_preferences_context", "")

        # menu-query uses candidates list — ALWAYS from context, never from LLM
        # (the LLM doesn't know the actual menu items and would invent them)
        if skill_name in ("menu-query", "rag-retrieve"):
            input_data["candidates"] = context.get("candidates", [])

        # order-flow uses session context
        if skill_name == "order-flow":
            if "summary_conversation" not in input_data:
                input_data["summary_conversation"] = context.get("summary_conversation", "")


# Expose module-level constants as class attributes so tests can use
# both ``SkillToolAdapter._ADD_ITEM_TOOL`` and direct imports.
SkillToolAdapter._ADD_ITEM_TOOL = _ADD_ITEM_TOOL
SkillToolAdapter._REMOVE_ITEM_TOOL = _REMOVE_ITEM_TOOL
SkillToolAdapter._UPDATE_ITEM_TOOL = _UPDATE_ITEM_TOOL
SkillToolAdapter._GET_ORDER_TOOL = _GET_ORDER_TOOL
SkillToolAdapter._CONFIRM_ORDER_TOOL = _CONFIRM_ORDER_TOOL
SkillToolAdapter._CANCEL_ORDER_TOOL = _CANCEL_ORDER_TOOL
SkillToolAdapter._UPDATE_ORDER_TOOL = _UPDATE_ORDER_TOOL
SkillToolAdapter._SET_FIELD_NOTE_TOOL = _SET_FIELD_NOTE_TOOL
SkillToolAdapter._BUSINESS_INFO_TOOL = _BUSINESS_INFO_TOOL
SkillToolAdapter._DOC_QUERY_TOOL = _DOC_QUERY_TOOL
SkillToolAdapter._SYNTHETIC_ORDER_TOOLS = _SYNTHETIC_ORDER_TOOLS
SkillToolAdapter._SYNTHETIC_ORDER_TOOL_MAP = _SYNTHETIC_ORDER_TOOL_MAP

# Expose _AUTOMATIC_SKILLS at module level for direct import
_AUTOMATIC_SKILLS = SkillToolAdapter._AUTOMATIC_SKILLS
