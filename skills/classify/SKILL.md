---
name: classify
display: Clasificador de Intención
trigger: "ÚSALA SOLO EN CASOS COMPLEJOS — Cuando el mensaje del usuario tenga MÚLTIPLES intenciones mezcladas o no puedas determinar claramente qué quiere. NO la uses para mensajes simples como 'hola', 'la carta', 'una pechuga', 'a la plancha'."
intents: [classify]
deterministic: false
dependencies: [classifier]
version: "0.1.0"
---

# Classify Skill — L2 Activation

Wraps `HybridClassifier` for intent detection and topic classification.

## Contract

- **Input**: `{"message": str, "summary_order": str, "summary_conversation": str}`
- **Output**: `{"classification": dict, "requires_RAG": bool, "requires_reconcilier": bool}`
- **Behavior**: ÚSALA SOLO EN CASOS COMPLEJOS — mensajes con múltiples intenciones mezcladas (ej: preguntar por menú, horarios, métodos de pago Y además querer ordenar). Para mensajes simples, el Planner puede resolverlos sin clasificar.
- **Errors**: `StageExecutionError` on LLM failure or invalid input.
