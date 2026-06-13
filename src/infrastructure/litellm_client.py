"""
LiteLLM client implementation — unified wrapper for all providers.

Replaces the ABC-based LLMClient + 6 provider implementations with a single
class that uses LiteLLM's acompletion() API for cross-provider compatibility.

Model format: ``"provider/model_name"`` (e.g. ``"deepseek/deepseek-chat"``,
``"openai/gpt-4o"``, ``"anthropic/claude-3-5-sonnet-20241022"``).

API keys are auto-read from environment variables by LiteLLM
(``DEEPSEEK_API_KEY``, ``OPENAI_API_KEY``, ``ANTHROPIC_API_KEY``, etc.).
"""
import json
import logging
import os
import re
from typing import Any, AsyncGenerator, Dict, List, Optional, Type, Union

from pydantic import BaseModel

from langfuse import observe


logger = logging.getLogger("LiteLLMClient")


class LiteLLMClient:
    """
    Unified LLM client using LiteLLM's ``acompletion()``.

    Supports all providers that LiteLLM supports. This single class
    replaces the previous ABC + 6 provider implementations.

    Args:
        api_key: Optional API key. If ``None``, LiteLLM reads from env.
        **kwargs: Additional arguments forwarded to every LiteLLM call.
                  Common: ``api_base`` (custom base URL), ``organization``,
                  ``additional_headers``, etc.
    """

    def __init__(self, api_key: Optional[str] = None, **kwargs: Any) -> None:
        try:
            import litellm
            litellm.drop_params = True
            self._litellm = litellm
        except ImportError:
            raise ImportError("litellm package not installed. Run: pip install litellm")

        # ── Propagate API keys from pydantic-settings to os.environ ──
        # pydantic-settings reads .env into Settings but does NOT set
        # os.environ. LiteLLM reads API keys from environment variables
        # (e.g. GEMINI_API_KEY, OPENAI_API_KEY), so we propagate them here.
        from src.config.environment import settings as _env

        _propagate_map: dict[str, str] = {
            "GEMINI_API_KEY": _env.gemini_api_key,
            "DEEPSEEK_API_KEY": _env.deepseek_api_key,
            "OPENAI_API_KEY": _env.openai_api_key,
            "ANTHROPIC_API_KEY": _env.anthropic_api_key,
            "GROQ_API_KEY": _env.groq_api_key,
            "MINIMAX_API_KEY": _env.minimax_api_key,
        }
        for var, val in _propagate_map.items():
            if val:
                os.environ.setdefault(var, val)

        # ── Propagate Langfuse credentials for LiteLLM callback ──
        # litellm.success_callback = ["langfuse"] reads creds from os.environ,
        # but pydantic-settings only sets them in the Settings object.
        if _env.langfuse_public_key:
            os.environ.setdefault("LANGFUSE_PUBLIC_KEY", _env.langfuse_public_key)
            os.environ.setdefault("LANGFUSE_SECRET_KEY", _env.langfuse_secret_key or "")
            os.environ.setdefault("LANGFUSE_HOST", _env.langfuse_host or "https://us.cloud.langfuse.com")

        # ── Monkey-patch langfuse.version for LiteLLM compatibility ──
        # langfuse 4.7.1 exposes version as langfuse.__version__ (not
        # langfuse.version.__version__). LiteLLM's LangfusePromptManagement
        # expects the latter. Patch it before registering the callback.
        if _env.langfuse_public_key:
            import functools as _functools
            import langfuse as _langfuse
            import types as _types

            if not hasattr(_langfuse, "version"):
                _langfuse.version = _types.ModuleType("version")
                _langfuse.version.__version__ = _langfuse.__version__

            # ── Monkey-patch Langfuse.__init__ to strip sdk_integration ──
            # Langfuse 4.x removed the `sdk_integration` kwarg, but LiteLLM
            # still passes it when it detects langfuse SDK >= 2.6.0 (always
            # true for 4.x). Without this patch the callback crashes with:
            #   TypeError: Langfuse.__init__() got an unexpected keyword
            #   argument 'sdk_integration'
            _orig_init = _langfuse.Langfuse.__init__

            @_functools.wraps(_orig_init)
            def _patched_init(monkey_self, *args, **kwargs):
                kwargs.pop("sdk_integration", None)
                return _orig_init(monkey_self, *args, **kwargs)

            _langfuse.Langfuse.__init__ = _patched_init

        # NOTE: LiteLLM's built-in langfuse callback (success_callback=["langfuse"])
        # is NOT registered because Langfuse 4.x removed the .trace() API that
        # LiteLLM's LangFuseLogger depends on. The @observe() decorator on
        # chat_completion() already creates traces via OpenTelemetry.
        # Token usage data is logged to console via _log_cost().

        self._extra_kwargs: Dict[str, Any] = {}

        if api_key is not None:
            self._extra_kwargs["api_key"] = api_key

        # Merge any extra kwargs (e.g. api_base for custom endpoint)
        self._extra_kwargs.update(kwargs)

    # ──────────────────────────────────────────────────────────────
    # Public API  (matches the LLMClient ABC signatures exactly)
    # ──────────────────────────────────────────────────────────────

    @observe(name="chat_completion")
    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        model: str = "deepseek/deepseek-chat",
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        stream: bool = False,
        response_format: Optional[Dict] = None,
        output_format: Optional[Type[BaseModel]] = None,
        parse_response: bool = True,
        tools: Optional[List[Dict]] = None,
        tool_choice: Optional[str] = None,
        tool_choice_required: bool = False,
    ) -> Union[str, BaseModel, Dict[str, Any]]:
        """
        Create a chat completion using LiteLLM.

        Returns:
            - ``str`` — plain-text response.
            - ``BaseModel`` — parsed structured output when ``output_format``
              is set and parsing succeeds.
            - ``Dict`` — tool-calls result when tools finish with
              ``"tool_calls"``.
        """
        params: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "stream": stream,
        }

        if max_tokens is not None:
            params["max_tokens"] = max_tokens

        # ── Structured output (output_format) ──
        # Inject JSON schema into system message rather than sending
        # response_format as an API parameter — not all providers support
        # the structured-output API natively, and our _parse_response
        # fallback can still recover JSON from plain text.
        if output_format:
            schema_prompt = self._build_structured_prompt(output_format)
            if messages and messages[0].get("role") == "system":
                messages[0]["content"] = messages[0]["content"] + "\n\n" + schema_prompt
            else:
                messages = [{"role": "system", "content": schema_prompt}] + messages
            params["messages"] = messages
        elif response_format:
            params["response_format"] = response_format

        # ── Tools / Function Calling ──
        if tools:
            params["tools"] = tools
            if tool_choice_required:
                params["tool_choice"] = "required"
            elif tool_choice:
                params["tool_choice"] = tool_choice

        # Merge extra kwargs (api_key, api_base, etc.)
        params.update(self._extra_kwargs)

        # Internal metadata (popped before the real API call)
        params["_output_format"] = output_format
        params["_parse_response"] = parse_response
        params["_tools"] = bool(tools)

        if stream:
            return await self._stream_completion(params)  # type: ignore[return-value]
        else:
            return await self._regular_completion(params)

    async def extract_json(
        self,
        prompt: str,
        system_message: Optional[str] = None,
        temperature: float = 0.1,
    ) -> Dict:
        """Extract structured JSON from a natural-language prompt."""
        messages: List[Dict[str, str]] = []

        if system_message:
            messages.append({"role": "system", "content": system_message})

        messages.append({"role": "user", "content": prompt})

        response = await self.chat_completion(
            messages=messages,
            temperature=temperature,
            response_format={"type": "json_object"},
        )

        try:
            return json.loads(response)
        except json.JSONDecodeError:
            json_match = re.search(r"\{.*\}", response, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
            return {"error": "Failed to parse JSON", "raw_response": response}

    async def analyze_with_schema(
        self,
        user_message: str,
        schema_prompt: str,
        schema_example: Optional[str] = None,
    ) -> Dict:
        """Analyze a user message and return structured data matching a schema."""
        system_prompt = f"""Analyze the user message and return JSON.

{schema_prompt}

{"Example output: " + schema_example if schema_example else ""}

Return ONLY valid JSON."""

        return await self.extract_json(
            prompt=user_message,
            system_message=system_prompt,
            temperature=0.1,
        )

    # ──────────────────────────────────────────────────────────────
    # Internal completion helpers
    # ──────────────────────────────────────────────────────────────

    async def _regular_completion(
        self, params: Dict[str, Any]
    ) -> Union[str, BaseModel, Dict[str, Any]]:
        """Handle a non-streaming completion."""
        output_format = params.pop("_output_format", None)
        parse_response = params.pop("_parse_response", True)
        has_tools = params.pop("_tools", False)

        response = await self._litellm.acompletion(**params)

        choice = response.choices[0]
        content = choice.message.content
        finish_reason = choice.finish_reason
        model_used = params.get("model", "unknown")

        # ── Cost tracking ──
        self._log_cost(response, model_used)

        # ── Reasoning content (thinking / reasoning mode) ──
        reasoning_content = self._extract_reasoning_content(choice.message)

        # ── Tool calling ──
        if finish_reason == "tool_calls" and choice.message.tool_calls:
            return self._build_tool_calls_result(
                choice.message.tool_calls,
                content,
                model_used,
                reasoning_content,
            )

        # ── Content logging ──
        if not content:
            logger.warning(
                "LiteLLM returned empty content | "
                "model=%s finish_reason=%s output_format=%s tools=%s",
                model_used,
                finish_reason,
                "yes" if output_format else "no",
                "yes" if has_tools else "no",
            )
        else:
            logger.info(
                "LiteLLM OK | model=%s finish_reason=%s content_len=%d",
                model_used,
                finish_reason,
                len(content),
            )

        # ── Structured output parsing ──
        if output_format and parse_response:
            return self._parse_response(content, output_format)

        return content

    async def _stream_completion(
        self, params: Dict[str, Any]
    ) -> AsyncGenerator[str, None]:
        """Handle streaming completion — yields content deltas."""
        params.pop("_output_format", None)
        params.pop("_parse_response", None)
        params.pop("_tools", None)

        stream = self._litellm.acompletion(**params)

        async for chunk in stream:
            if chunk.choices[0].delta.content is not None:
                yield chunk.choices[0].delta.content

    # ──────────────────────────────────────────────────────────────
    # Tool-call result builder
    # ──────────────────────────────────────────────────────────────

    def _build_tool_calls_result(
        self,
        tool_calls_raw: Any,
        assistant_content: Optional[str],
        model_used: str,
        reasoning_content: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Build the standard tool_calls dict consumed by ToolOrchestrator."""
        tool_calls = []
        for tc in tool_calls_raw:
            try:
                args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                args = {"_raw": tc.function.arguments}
            tool_calls.append({
                "id": tc.id,
                "name": tc.function.name,
                "arguments": args,
            })

        logger.info(
            "LiteLLM tool_calls | model=%s calls=%d tools=%s",
            model_used,
            len(tool_calls),
            [t["name"] for t in tool_calls],
        )

        result: Dict[str, Any] = {
            "finish_reason": "tool_calls",
            "tool_calls": tool_calls,
            "assistant_message": assistant_content or "",
        }
        if reasoning_content:
            result["reasoning_content"] = reasoning_content
        return result

    # ──────────────────────────────────────────────────────────────
    # Cost & reasoning helpers
    # ──────────────────────────────────────────────────────────────

    @staticmethod
    def _log_cost(response: Any, model_used: str) -> None:
        """Log response cost when LiteLLM provides it."""
        try:
            cost = response._hidden_params.get("response_cost")
            if cost is not None:
                logger.info("LiteLLM cost | model=%s cost=$%.6f", model_used, cost)
        except AttributeError:
            pass

    @staticmethod
    def _extract_reasoning_content(message: Any) -> Optional[str]:
        """Extract reasoning/thinking content if the model provides it."""
        if hasattr(message, "reasoning_content"):
            return message.reasoning_content
        if message.model_extra:
            return message.model_extra.get("reasoning_content")
        return None

    # ──────────────────────────────────────────────────────────────
    # Response parsing & prompt builders
    # (identical logic to LLMClient ABC lines 54-88)
    # ──────────────────────────────────────────────────────────────

    def _parse_response(
        self,
        content: str,
        output_format: Optional[Type[BaseModel]] = None,
    ) -> Union[str, BaseModel, None]:
        """Parse response content into a Pydantic model if requested.

        Returns ``None`` when content is empty/blank — the caller is
        responsible for handling the empty-response case gracefully.
        """
        if not content or not content.strip():
            return None

        if output_format:
            try:
                return output_format.model_validate_json(content)
            except Exception:
                json_match = re.search(r"\{.*\}", content, re.DOTALL)
                if json_match:
                    return output_format.model_validate_json(json_match.group())
                raise
        return content

    def _build_structured_prompt(self, output_format: Type[BaseModel]) -> str:
        """Build a system prompt that instructs the model to output valid JSON.

        The prompt includes the full ``model_json_schema()`` so the model
        knows the exact structure expected.
        """
        schema = output_format.model_json_schema()
        schema_str = json.dumps(schema, indent=2, ensure_ascii=False)

        return (
            "Your response MUST be only a valid JSON object that complies with "
            "the following JSON schema.\n"
            "Do not include any additional text, explanations, or markdown.\n\n"
            f"Required JSON schema:\n{schema_str}\n\n"
            "The JSON must have all required properties of the schema."
        )
