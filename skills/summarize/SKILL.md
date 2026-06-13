---
name: summarize
display: Resumen de Sesión
trigger: "after every response — fire-and-forget session summarization"
intents: [summarize]
deterministic: false
dependencies: [summarizer]
version: "0.1.0"
---

# Summarize Skill — L2 Activation

Fire-and-forget session summarization with completion guard (5s timeout → sync fallback).

## Contract

- **Input**: `{"session_id": str, "turn_number": int, "message": str, "focuses": list, "intents": list, "summary_order": str, "assistant_response": str}`
- **Output**: `{"success": bool, "fallback_used": bool}`
- **Behavior**: Attempts `ContextSummarizer.summarize_turn()` with `asyncio.timeout()` guard. On timeout or when no summarizer is configured, writes a synchronous fallback summary with turn data only.
- **Errors**: `StageExecutionError` on unexpected errors. Non-critical — entire skill is fire-and-forget.

## Completion Guard (S-P6-02)

Every turn produces a summary — either async via LLM or sync fallback:
1. Launch `summarize_turn()` with `asyncio.timeout(5.0)`
2. If LLM completes within 5s → success
3. If timeout → write sync fallback immediately
4. If no summarizer → write sync fallback immediately

## Example Fallback

```json
{"session_id": "s1", "turn_number": 3, "summary_text": "Turno 3: quiero dos tacos al pastor... | Asistente: Claro, dos tacos al pastor...", "current_order_state": "2x tacos al pastor"}
```
