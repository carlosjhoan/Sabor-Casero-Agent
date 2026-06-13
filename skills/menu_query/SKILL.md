---
name: menu-query
display: Consulta de Menú
trigger: "user pregunta por el menú, precios, ingredientes, métodos de cocción"
intents: [menu_query, price_check, ingredient_lookup]
deterministic: true
dependencies: [owl_client, owl_signal, ontology_gate]
version: "0.1.0"
---

# Menu-Query Skill — L2 Activation

Wraps `OwlSignal` + `OntologyValidationGate` for deterministic menu queries.

## Contract

- **Input**: `{"query": str, "candidates": list[str]}`
- **Output**: `{"items": list[dict], "match_type": "exact"|"partial"|"related"|"none"}`
- **Behavior**: Uses SPARQL against `menu.ttl` to score candidates. Exact match returns 1.0 and short-circuits. Partial/ingredient/method/synonym matches return 0.8–0.6.
- **Errors**: `StageExecutionError` on SPARQL failure. `OntologyGateError` when gate rejects all candidates.

## Fast Path

Phase 1 OWL exact match runs in <5ms — no LLM required. When a query matches an item name exactly, the skill returns immediately with the deterministic score.
