# Proposal: Dynamic Document Index

## Intent

`DocumentRegistry` hardcodes summary strings that go stale silently when document content changes (delivery prices, coverage zones, payment methods). This change makes the index self-healing: SHA256 change detection, automatic structure extraction, persistent cache.

## Scope

### In Scope
- **Content Analyzer** (new): regex header/section extraction, SHA256 fingerprinting
- **Document Cache** (new): JSON persistence at `data/cache/document_cache.json`, auto-invalidates on hash mismatch
- **Registry refactor**: replace hardcoded `summary`/`covered_topics` with dynamic derivation
- **Topic-to-doc mapping**: externalized to `data/config/topic_document_map.yaml`
- **Optional LLM enrichment**: narrative summary on document change (1 call per changed doc, cached)
- **Consumer updates**: `hybrid.py`, `order_response_builder.py`, `vector_extractor.py`, `input_guard.py`

### Out of Scope
- LLM summary as required path (always optional, gated by flag)
- Classifier prompt format changes — only `{docs_summaries}` content changes
- ChromaDB re-indexing or RAG pipeline changes

## Capabilities

### New
- `document-index`: dynamic document indexing with structure extraction, fingerprint caching, configurable topic mapping

### Modified
- None — no spec-level behavior changes. Classifier unchanged; only its input derives dynamically.

## Approach

Three-layer design:

1. **Detection**: Content Analyzer reads documents, extracts markdown headers (`## Section`) and plain-text blocks via regex, computes SHA256. No LLM.
2. **Cache**: `document_cache.json` stores `{filename: {hash, sections[], last_updated}}`. On load, hash mismatch → re-parse.
3. **Registry**: `get_all_summaries()` derives output from section headers + topic mapping config instead of static strings.

Flow: startup → Cache → per doc: hash match → cached / mismatch → parse, hash, save → Registry builds section index → inject via same prompt variable.

## Affected Areas

| Area | Impact |
|------|--------|
| `src/core/knowledge/registry.py` | Modified — remove hardcoded summaries |
| `src/core/knowledge/content_analyzer.py` | **New** |
| `src/core/knowledge/document_cache.py` | **New** |
| `data/cache/document_cache.json` | **New** (gitignored) |
| `data/config/topic_document_map.yaml` | **New** |
| Consumers (4 files) | Modified — minor signature updates |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Regex misses doc format variants | Medium | Test all 4 docs; fallback to full-text if extraction fails |
| Cache corruption (partial write) | Low | Atomic write via temp + rename |

## Rollback

Revert `registry.py` to hardcoded list. Delete `content_analyzer.py`, `document_cache.py`, `data/cache/`, and `data/config/topic_document_map.yaml`. Revert consumer changes. Format of `get_all_summaries()` is identical — only content source changes.

## Dependencies

None external. Standard library only: `hashlib`, `re`, `json`, `pathlib`.

## Success Criteria

- [ ] All 4 docs parsed with correct section extraction (tested)
- [ ] Document edits detected via hash mismatch (test: modify file, restart, verify cache invalidation)
- [ ] `get_all_summaries()` returns same format as before (different content, same structure)
- [ ] Classifier still produces correct topic classifications with dynamic summaries
- [ ] Topic→doc mapping works from external YAML matching current hardcoded behaviour
