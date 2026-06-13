# Tasks: agent-memory-and-pipeline (Re-Plan — Skill Architecture)

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~2,800–3,800 (40+ new files, 10 modified, ~20 test files) |
| 400-line budget risk | **High** |
| Chained PRs recommended | Yes |
| Delivery strategy | ask-on-risk |
| Chain strategy | stacked-to-main |

Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: stacked-to-main
400-line budget risk: High

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|------|------|-----------|-------|
| 1 | P1 Foundation: errors, validation, SkillResult, null/empty fix | PR 1 | Base: main. ~300 lines. Standalone. |
| 2 | P2 Skill Framework: orchestrator, registry, BaseSkill | PR 2 | Base: main. ~400 lines. Independent. |
| 3 | P3 Checkpointing + Observability | PR 3 | Base: main. ~300 lines. Independent. |
| 4 | P4 Semantic Memory: MemoryHub, stores, entity extraction | PR 4 | Base: main. ~350 lines. Independent. |
| 5 | P5a OWL + menu-query: ontology, OwlSignal, gate, skill | PR 5a | Base: main. ~400 lines. Depends on P2+P4. |
| 6 | P5b RAG v2 + rag-retrieve: BM25, entity, RRF, cross-encoder | PR 5b | Base: main. ~400 lines. Depends on P5a. |
| 7 | P6 Full Orchestration: remaining 5 skills + assistant.py | PR 6 | Base: main. ~450 lines. Depends on all prior. |

P1–P4 are technically independent and may be parallelized using base `Exception` temporarily.

---

## Phase 1: Foundation (P1)

- [x] 1.1 Define `PipelineError` hierarchy in `src/core/agent/exceptions.py` — `StageExecutionError`, `ValidationGateError`, `CheckpointError`, `MemoryHubError`, `CacheError`, `OntologyGateError`
- [x] 1.2 Add `SkillResult[T]` to `stage_result.py` with `skill_name`, `skill_version`, `metadata`; adapt `StageResult` as backward-compat alias
- [x] 1.3 Create `ValidationGates` (`src/core/agent/validation_gates.py`) — Pydantic validators rejecting nulls/empty per-stage
- [x] 1.4 Fix empty response: guard replaces `""` with `FALLBACK_ERROR` + `EmptyResponseError` log
- [x] 1.5 Fix hardcoded `service_type="delivery"` — derive from `UserPreferences.get_best_guess()` or clarify
- [x] 1.6 Replace bare `except Exception` with stage-level typed handlers per criticality rubric
- [x] 1.7 Add `pipeline_validation_enabled`, `service_type_inference_enabled` flags to `environment.py`
- [x] 1.8 Tests: S-P1-01 (null → ValidationError), S-P1-02 (service_type inference), S-P1-03 (typed error propagation)

## Phase 2: Skill Framework (P2)

- [x] 2.1 Create `BaseSkill` abstract class (`src/core/agent/skill_base.py`) — `load/run/unload` + versioning from frontmatter
- [x] 2.2 Create `SkillRegistry` (`src/core/agent/skill_registry.py`) — L1 frontmatter index, path resolution, discovery
- [x] 2.3 Create `SkillOrchestrator` (`src/core/agent/orchestrator.py`) — `load_skill()` meta-tool, lifecycle mgmt, intent-based decision engine
- [x] 2.4 Create skill dir structure: `skills/<name>/{SKILL.md, __init__.py, tests/}` with SKILL.md YAML frontmatter template
- [x] 2.5 Add `skill_framework_enabled` flag to `environment.py`
- [x] 2.6 Tests: registry index/parse, BaseSkill lifecycle, orchestrator decide_skills(intent), SkillResult success/fail/merge

## Phase 3: Checkpointing + Observability (P3)

- [x] 3.1 Create `CheckpointManager` (`src/core/agent/checkpoint.py`) — save/load/clear per-skill, persisted to `data/checkpoints/{session_id}.json`
- [x] 3.2 Create `TraceContext` (`src/core/agent/trace_context.py`) — `contextvars`-based `trace_id`, `@span` decorator with timing + structured event log
- [x] 3.3 Add `metadata` field to `SkillResult` — carries `checkpoint_id`, `trace_id`, `duration_ms`
- [x] 3.4 Add latency diagnostic: mean/p50/p95/p99 per skill over last N=100
- [x] 3.5 Add `checkpointing_enabled` flag to `environment.py`
- [x] 3.6 Tests: S-P3-01 (crash resume golden), S-P3-02 (trace_id propagation), latency accuracy

## Phase 4: Semantic Memory (P4)

- [x] 4.1 Define `Entity` Pydantic model in `src/core/memory/domain/models_memory.py`
- [x] 4.2 Create `ChromaMemoryRepository` (`src/core/memory/infrastructure/chroma_memory_repository.py`) — `memory_semantic` collection, idempotent upsert by `(user_id, type, value)`
- [x] 4.3 Create `SemanticStore` (`src/core/memory/domain/semantic_store.py`) — store_entity, query_by_semantic, query_by_entity, extract_from_turn
- [x] 4.4 Create `MemoryHub` facade (`src/core/memory/domain/memory_hub.py`) — store/query/recall delegating to internal stores
- [x] 4.5 Add entity extraction callback in `context_summarizer.py` — structured facts from conversation turns
- [x] 4.6 Wire `UserPreferences.save()` → sync to `MemoryHub.semantic`
- [x] 4.7 Add `semantic_memory_enabled` flag to `environment.py`
- [x] 4.8 Tests: S-P2-01 (cross-session recall), S-P2-02 (dietary propagation), synonym cosine ≥0.75, idempotent upsert

## Phase 5: Domain Skills — OWL + RAG v2 (P5)

- [x] 5.1 Enrich `data/ontology/menu.ttl` — `CookingMethod`/`Ingredient` classes, `hasCookingMethod`/`hasMainIngredient` properties, link existing items
- [x] 5.2 Create `data/ontology/ontology_synonyms.json` — term→ingredient/item/method mapping
- [x] 5.3 Create `OwlSignal` (`src/core/extractor/owl_signal.py`) — score_candidates (exact=1.0 → none=0.0), expand_query, validate_candidates
- [x] 5.4 Create `OntologyValidationGate` (`src/core/extractor/ontology_validation_gate.py`) — exact pass, related tag/boost, invented penalize, all-rejected→`OntologyGateError`
- [x] 5.5 Create `BM25Retriever` (`src/core/extractor/bm25_retriever.py`) — keyword index via `rank_bm25`
- [x] 5.6 Create `EntityRetriever` (`src/core/extractor/entity_retriever.py`) — scores by semantic memory entity match
- [x] 5.7 Create `RRFFuser` (`src/core/extractor/rrf_fuser.py`) — 4-signal fusion (dense+BM25+entity+OWL), k=60
- [x] 5.8 Create `CrossEncoderReranker` (`src/core/extractor/cross_encoder_reranker.py`) — rerank top-20→top-5 via `cross-encoder/ms-marco-MiniLM-L-6-v2` + ONNX
- [x] 5.9 Add `retrieve_v2()` to `RetrieverInterface` with fused score output
- [x] 5.10 Wire 3-phase RAG in `composite_retriever.py` (OWL exact fast-path → multi-signal RRF → gate); behind `rag_v2_enabled`
- [x] 5.11 Create `skills/menu_query/` — `__init__.py` + `SKILL.md` wrapping OWL signal with ontology validation
- [x] 5.12 Create `skills/rag_retrieve/` — `__init__.py` + `SKILL.md` wrapping RAG v2 pipeline
- [x] 5.13 Add `rag_v2_enabled` flag to `environment.py`
- [x] 5.14 Tests: OWL signal all match types (exact/partial/ingredient/method/synonym/none), ontology gate outcomes (S-P4-02), RAG v2 integration (S-P4-03), multi-signal recall precision

## Phase 6: Full Orchestration — Remaining Skills + Wiring (P6)

- [x] 6.1 Create `skills/classify/` — wrapper around HybridClassifier, `__init__.py` + `SKILL.md`
- [x] 6.2 Create `skills/order-flow/` — wrapper around OrderOrchestrator + ActionPlanner, `__init__.py` + `SKILL.md`
- [x] 6.3 Create `skills/response-build/` — wrapper around ResponseBuilder, `__init__.py` + `SKILL.md`
- [x] 6.4 Create `skills/memory-store/` — turn persistence + entity extraction, `__init__.py` + `SKILL.md`
- [x] 6.5 Create `skills/summarize/` — session summarization with completion guard (5s timeout) + sync fallback, `__init__.py` + `SKILL.md`
- [x] 6.6 Wire `SkillOrchestrator` + `MemoryHub` + `CheckpointManager` into `assistant.py` — replace hardcoded stage calls with orchestration loop
- [x] 6.7 Add `skills_enabled` flag to `environment.py`
- [x] 6.8 Tests: S-P6-01 (specialist delegation via skills), S-P6-02 (summarization guard timeout), S-P6-03 (concurrent semaphore), full E2E with all skills
