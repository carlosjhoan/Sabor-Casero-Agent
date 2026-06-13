---
name: memory-store
display: Almacenamiento en Memoria
trigger: "after every response — persists turn data and extracts entities"
intents: [memory_persist]
deterministic: true
dependencies: [memory_hub]
version: "0.1.0"
---

# Memory-Store Skill — L2 Activation

Persists conversation turns and extracts structured entities (preferences, dietary restrictions, etc.) via `MemoryHub.semantic.extract_from_turn()`.

## Contract

- **Input**: `{"user_id": str, "session_id": str, "turn_number": int, "user_message": str, "assistant_response": str}`
- **Output**: `{"entities_stored": int, "episode_id": str | None}`
- **Behavior**: Builds a `ConversationTurn` from the input, runs rule-based entity extraction, and persists each entity via `MemoryHub.store()`. Gracefully degrades when `memory_hub` is not configured.
- **Errors**: `StageExecutionError` on extraction failure. Non-critical — errors are swallowed in production.

## Guard

Skipped when `user_message` is empty. No-op when `memory_hub` is not configured.
