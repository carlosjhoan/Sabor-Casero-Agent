---
name: search-docs
display: Búsqueda en Documentos
trigger: "user necesita buscar información específica dentro de un documento en particular (horarios, zonas de entrega, políticas)"
intents: [info_request, document_search]
deterministic: false
dependencies: [retriever]
version: "0.1.0"
---

# Search-Docs Skill — Document-Scoped Semantic Search

Wraps `HybridRetriever._get_context()` with a `where={"source": doc_name}`
filter for targeted document retrieval. Returns top-3 chunks from the
specified document.

## Contract

- **Input**: `{"query": str, "doc_name": str}`
- **Output**: `{"result": str, "chunks_found": int, "summary": str}`
- **Pipeline**:
  1. Embed query → query_vector
  2. ChromaDB query with `where={"source": doc_name}`
  3. Cross-encoder rerank → top 3 chunks
  4. Flatten to string

## Errors

- `RetrieverNotAvailable`: retriever not in context → `SkillResult.fail`
- `DocumentNotFound`: unknown doc_name → empty result, not error
