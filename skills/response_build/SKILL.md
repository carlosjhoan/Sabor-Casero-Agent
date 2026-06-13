---
name: response-build
display: Construcción de Respuesta
trigger: "always — every message needs a response"
intents: [respond]
deterministic: false
dependencies: [response_builder]
version: "0.1.0"
---

# Response-Build Skill — L2 Activation

Wraps `ResponseBuilder.build_hybrid()` for final response generation.

## Contract

- **Input**: `{"classification": ..., "order_state": ..., "orchestrator_result": ..., "message": str, "summary_conversation": str, "tracker": ..., "brand_voice_path": str, "prompt_template_path": str, "settings": ...}`
- **Output**: `{"response": str}`
- **Behavior**: Delegates to `ResponseBuilder` which mixes order state + RAG results + brand voice via LLM. Empty/whitespace response triggers `FALLBACK_ERROR` guard.
- **Errors**: `StageExecutionError` on LLM failure or invalid input.

## Always Loaded

This skill runs on EVERY message — every user message gets a response.
