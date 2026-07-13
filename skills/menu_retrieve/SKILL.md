---
name: rag-retrieve
display: Recuperación RAG v2
trigger: "user busca información del menú, ingredientes, platos"
intents: [info_request, menu_query, ingredient_lookup]
deterministic: false
dependencies: [owl_client, owl_signal, memory_hub, retriever, bm25_retriever, entity_retriever, rrf_fuser, cross_encoder, ontology_gate]
version: "0.1.0"
---

# RAG-Retrieve Skill — L2 Activation

Wraps the full RAG v2 pipeline: dense + BM25 + entity + OWL → RRF → cross-encoder → ontology validation gate.

## Contract

- **Input**: `{"query": str, "candidates": list[str], "details": list[dict]}`
- **Output**: `{"items": list[dict], "pipeline": "full"|"fast_path"|"owl_only"|"none"}`
- **Pipeline**:
  1. Phase 1: OWL exact match (<5ms fast-path short-circuit)
  2. Phase 2: Multi-signal RRF (dense + BM25 + entity + OWL) → cross-encoder rerank
  3. Phase 3: Ontology Validation Gate (hallucination firewall)

## Errors

- `OntologyGateError`: All candidates rejected by ontology → clarification fallback
- `StageExecutionError`: Component failure → graceful degradation
