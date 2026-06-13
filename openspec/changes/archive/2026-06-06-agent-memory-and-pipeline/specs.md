# Delta Specs: agent-memory-and-pipeline

## Overview

These specs define the behavioral changes across 6 phases (P1–P6) for the
Sabor Casero assistant ("Luz Stella"). Each phase addresses a set of pipeline
failures identified in the conversation log audit of 35 files.

**Pipeline context**: `SaborCaseroAssistant.process_message()` currently runs 9
stages (0–8) with mixed criticality, no checkpointing, no trace propagation,
bare `except Exception` error handling, and fire-and-forget summarization.

---

## Phase P1: Foundation

| Field | Value |
|-------|-------|
| **Capability** | Error hierarchy, validation gates, null/empty fix, `service_type` fix |
| **Issues fixed** | 1 (null crisis), 2 (empty response), 7 (hardcoded service_type), 8 (errors swallowed), 13 (summarization), 14 (structured memory) |

### Requirements

| ID | Description | Strength |
|----|-------------|----------|
| FR-P1-01 | Define `PipelineError(Exception)` hierarchy with subtypes: `StageError`, `ValidationError`, `GuardRejectionError`, `RetryExhaustedError`, `CheckpointError`, `MemoryError`. Each carries `stage_name`, `error_code`, `timestamp`. | MUST |
| FR-P1-02 | Every `StageResult[T]` MUST use Pydantic for its value type `T` (stage contract schema). `StageResult.fail()` always carries a `PipelineError` subtype, never a bare string. | MUST |
| FR-P1-03 | `assistant_response` MUST never be empty when `success=true`. If response builder returns `""`, pipeline replaces it with `FALLBACK_ERROR` and logs `EmptyResponseError`. | MUST |
| FR-P1-04 | `service_type` MUST be derived from `UserPreferences.get_best_guess("service_type")` or explicitly clarified. Hardcoded `"delivery"` default is REMOVED. | MUST |
| FR-P1-05 | No bare `except Exception: continue` in any stage. Every exception produces a typed `PipelineError` and a structured JSON log entry. | SHALL NOT |
| FR-P1-06 | Outer `try/except` in `process_message()` is replaced with stage-level typed handlers per the criticality rubric. | MUST |

### Scenarios

**S-P1-01 — Null field detection**:
- GIVEN a classifier response with all fields null and `success=true`
- WHEN result proceeds to response generation
- THEN the validation gate rejects `StageResult` with `ValidationError(error_code="NULL_FIELDS")`
- AND pipeline returns `FALLBACK_ERROR` with `pipeline_error` containing the error code

**S-P1-02 — Service type inference**:
- GIVEN a user with `address` stored in `UserPreferences` (confidence > 0.7)
- WHEN they start ordering without specifying service type
- THEN `service_type` is set to "delivery" with prompt "¿Confirmas delivery a [address]?"
- AND pipeline never defaults to delivery without user confirmation

**S-P1-03 — Typed error propagation in RAG**:
- GIVEN a ChromaDB connection timeout during RAG stage
- WHEN the timeout exception is caught
- THEN it wraps as `StageError(stage="rag", error_code="RAG-001", cause=ChromaDBTimeoutError)`
- AND structured log emits: `{"trace_id": "...", "stage": "rag", "error_code": "RAG-001", "duration_ms": 5230}`

### Acceptance Criteria
- Zero bare `except Exception` remaining in `assistant.py`
- `assistant_response` never empty when `success=true` (mutation test)
- `service_type` never defaults to "delivery" without user context
- Each `StageResult.fail()` carries a `PipelineError` subtype, not raw string
- All 360 existing tests pass with zero regressions

### Dependencies
- Existing `StageResult[T]` (strengthen with Pydantic type binding)
- Pydantic (already installed)
- `UserPreferences.load()` (exists, needs `service_type` inference path)

### Non-Requirements
- No new pipeline stages added
- No message flow changes between stages
- No checkpointing (P3)
- No semantic/episodic/procedural memory

---

## Phase P2: Semantic Memory

| Field | Value |
|-------|-------|
| **Capability** | `MemoryHub` base, semantic collection (user facts, preferences, dietary), entity extraction, entity-aware query, merge with `UserPreferences` |
| **Issues fixed** | 6 (semantic memory gap), 10 (entity grounding) |

### Requirements

| ID | Description | Strength |
|----|-------------|----------|
| FR-P2-01 | `MemoryHub` class with `store(entity)`, `query(text, top_k)`, `recall(entity_id)`, `delete(entity_id)`. Backed by ChromaDB collections. | MUST |
| FR-P2-02 | Two ChromaDB collections: `semantic_facts` (user statements) and `semantic_preferences` (inferred preferences with confidence). | MUST |
| FR-P2-03 | Entity extraction pipeline identifies structured facts from conversation turns: `{type, value, user_id, timestamp, session_id}`. Types: `protein_pref`, `avoid_ingredient`, `extra_item`, `address`, `payment_method`, `dietary_restriction`. | MUST |
| FR-P2-04 | `MemoryHub.query("lechuga")` returns semantically matched facts using embedding cosine similarity. Synonyms ("lechuga" → "ensalada") score ≥0.75. | MUST |
| FR-P2-05 | `UserPreferences` JSON remains source of truth for Beta-Binomial inference. Semantic memory is a view/search layer — writes go to BOTH. | SHALL |
| FR-P2-06 | Storing the same entity twice updates timestamp + count, never duplicates. Idempotent by `(user_id, type, value)` composite key. | MUST |

### Scenarios

**S-P2-01 — Cross-session preference recall**:
- GIVEN user says "carne bien asada" in session 1
- WHEN entity pipeline stores `{type:"protein_pref", value:"carne bien asada", user_id:"u1"}`
- AND user returns in session 2 and starts ordering
- THEN `MemoryHub.query("carne")` returns "carne bien asada" with score > 0.8
- AND response includes "¿La carne bien asada como siempre?"

**S-P2-02 — Dietary restriction propagation**:
- GIVEN user says "sin lactosa por favor" in session 1
- WHEN entity pipeline extracts `{type:"avoid_ingredient", value:"lactosa"}`
- AND stored in both `UserPreferences` and `MemoryHub`
- THEN session 2 recommendations exclude dairy dishes
- AND response says "Recordá que pediste sin lactosa. ¿Seguimos igual?"

### Acceptance Criteria
- `MemoryHub.store(entity)` persists to ChromaDB, retrievable via `query(text)`
- Synonym query returns cosine similarity ≥ 0.75
- User fact surfaces in session 2 without re-asking
- `UserPreferences` JSON unchanged — no schema migration needed
- All 360 existing tests pass

### Dependencies
- ChromaDB ≥0.6.0 (collection metadata API)
- `MemoryHub` class (new, domain layer)
- Entity extraction module (new, application layer)
- `UserPreferences` (existing, no schema change)

### Non-Requirements
- No episodic memory (P4)
- No procedural memory (P5)
- No cross-encoder reranking
- No changes to `UserPreferences` serialization format

---

## Phase P3: Checkpointing + Observability

| Field | Value |
|-------|-------|
| **Capability** | Per-stage checkpoint save/restore, crash resume, `trace_id` + span propagation, structured event log, latency breakdown |
| **Issues fixed** | 9 (waste on crash), 12 (can't debug latency) |

### Requirements

| ID | Description | Strength |
|----|-------------|----------|
| FR-P3-01 | Each stage emits a checkpoint after success: `{stage_name, trace_id, value_hash, timestamp}` persisted to `data/checkpoints/{session_id}.json`. | MUST |
| FR-P3-02 | On crash restart, coordinator loads last checkpoint and resumes from that stage — stages before the checkpoint are NOT re-executed. | MUST |
| FR-P3-03 | `trace_id` (UUID v4) generated per `process_message()` call, propagated via `contextvars` through all stages. | MUST |
| FR-P3-04 | Each stage records a span: `{trace_id, stage_name, start_ms, end_ms, duration_ms, success, error_code}`. | MUST |
| FR-P3-05 | Structured event log (JSON array per session) aggregates all spans, checkpoints, and errors — queryable by `trace_id`. | MUST |
| FR-P3-06 | A diagnostic method produces per-stage latency breakdown aggregated over last N=100 messages: mean, p50, p95, p99 per stage. | MUST |

### Scenarios

**S-P3-01 — Crash resume**:
- GIVEN pipeline processing a message completes stages 1–3
- WHEN process crashes during stage 4
- AND pipeline restarts for the same message
- THEN coordinator reads checkpoint for stage 3
- AND resumes at stage 4 without redoing stages 1–3
- AND final output is identical to full re-execution (golden test)

**S-P3-02 — Trace_id propagation**:
- GIVEN user message "quiero dos tacos"
- WHEN `process_message()` generates `trace_id="abc-123"`
- AND message passes through stages 0–8
- THEN every stage span and log entry includes `trace_id="abc-123"`
- AND response dict includes `trace_id` in metadata

### Acceptance Criteria
- Crash resume produces identical output to full pipeline (golden test)
- Per-stage span timing available in structured event log
- `trace_id` present in every stage result and log entry
- Latency breakdown reports accurate per-stage p50/p95/p99
- All 360 existing tests pass

### Dependencies
- `contextvars` (Python 3.13 stdlib)
- P1 (error hierarchy) for typed checkpoint exceptions
- Checkpoint directory `data/checkpoints/` (new)
- Session ID for checkpoint keying (already exists)

### Non-Requirements
- No APM platform (OpenTelemetry, DataDog, etc.)
- No distributed tracing across service boundaries
- No checkpoint GC/archival logic in MVP

---

## Phase P4: Episodic Memory + RAG v2

| Field | Value |
|-------|-------|
| **Capability** | Episode capture, time-range/topic/entity query, multi-signal RAG (dense + BM25 + entity → RRF → cross-encoder), menu hallucination fix |
| **Issues fixed** | 3 (menu hallucinations), 6 (episodic memory gap), 11 (RAG precision) |

### Requirements

| ID | Description | Strength |
|----|-------------|----------|
| FR-P4-01 | Episodes are contiguous turn groups with: `{session_id, start_time, end_time, topics[], entities[], outcome}`. Outcome: `order_placed`, `cancelled`, `abandoned`, `info_only`. | MUST |
| FR-P4-02 | Episode query supports filters: time range ("la semana pasada"), topic ("pedí pollo"), entity ("tacos"), outcome. Returns top-5 episodes ordered by relevance. | MUST |
| FR-P4-03 | RAG v2 pipeline: dense vector (ChromaDB) + BM25 (rank-bm25) + entity exact/synonym match + **OWL/SPARQL signal (menu.ttl)** → RRF (Reciprocal Rank Fusion) → cross-encoder reranking (`cross-encoder/ms-marco-MiniLM-L-6-v2`). **4 signals total**. | MUST |
| FR-P4-04 | RRF fusion combines K=20 from each signal; cross-encoder reranks to top-5. Pipeline behind feature flag `use_rag_v2` (default `False` in P4). | MUST |
| FR-P4-05 | RAG v2 has 3-phase flow: **Phase 1** = OWL exact match (fast path, <5ms), **Phase 2** = multi-signal retrieval (dense + BM25 + entity + OWL partial) → RRF → cross-encoder, **Phase 3** = `OntologyValidationGate` validates top-K against menu.ttl. | MUST |
| FR-P4-06 | Ontology enriched with `CookingMethod` class, `Ingredient` class, `hasCookingMethod` and `hasMainIngredient` properties in `menu.ttl`. Synonym mapping in `ontology_synonyms.json` for query expansion. | MUST |
| FR-P4-07 | OWL signal scoring: exact=1.0, partial=0.8, ingredient/cooking-method=0.7, synonym=0.6, no-match=0.0. Scores feed into RRF as deterministic rank positions. | MUST |
| FR-P4-08 | `OntologyValidationGate` outcomes: exact-match → confidence preserved; semantic-match (ingredient/method) → tagged "related", confidence boosted; no-match → penalized ×0.3 or removed; all-rejected → `OntologyGateError` raised → clarification fallback. | MUST |
| FR-P4-09 | Cross-encoder adds ≤500ms to pipeline latency (measured on CPU with ONNX runtime optimization). | SHOULD |

### Scenarios

**S-P4-01 — Episode recall by time**:
> **⚠️ DEPRECATED** — EpisodicStore was not implemented as standalone class. Episodic structure exists in `RecallContext` model only. Descoped per re-plan.
- GIVEN user asks "¿Qué pedí la semana pasada?"
- WHEN system queries episodic memory with `time_range="last 7d"`, `user_id="u1"`
- THEN it returns episodes matching the range
- AND formats: "El martes pediste 2 tacos al pastor, y el jueves una pechuga con frijoles."

**S-P4-02 — OWL hallucination gate: "pollo guisado" no existe**:
- GIVEN user asks "¿tienen pollo guisado?" (dish NOT in menu ontology)
- WHEN **Phase 1** (OWL exact match) runs SPARQL: `FILTER(CONTAINS(LCASE(?item), "pollo"))`
- AND OWL partial finds "pechuga a la plancha" (pollo → ingredient) → 0.7, "pechuga gratinada" → 0.7
- AND OWL finds NO "pollo guisado" in ontology → 0.0
- WHEN Phase 2 (RRF + cross-encoder) includes the OWL partial matches
- AND Phase 3 (Ontology Validation Gate) confirms: Pechuga items exist in menu.ttl → pass ✅
- AND "pollo guisado" = no match → removed from top-5 🚫
- THEN response says "No tenemos pollo guisado exacto, pero tenemos **Pechuga a la plancha** (pollo a la plancha) y **Pechuga gratinada**. ¿Te interesa alguna?"

**S-P4-03 — OWL ingredient expansion: "marrano"**:
- GIVEN user asks "¿algo como marrano tienen?"
- WHEN Phase 1 OWL exact finds nothing (no itemName "marrano")
- AND query expansion via `ontology_synonyms.json` maps "marrano" → `related_ingredients: ["cerdo"]`
- AND OWL partial runs SPARQL: `?s :hasMainIngredient :Cerdo` → "Lomo de cerdo asado a la plancha" (0.7), "Carnes mixtas en vegetales" (0.7)
- AND ontology synonym expansion catches related items → 0.6
- AND Phase 3 Gate tags these "related" (not exact) → confidence boosted
- THEN response says "No tenemos nada llamado 'marrano', pero tenemos opciones de cerdo: **Lomo de cerdo asado a la plancha** (corriente $13,500 / mini $12,000) y **Carnes mixtas en vegetales** con cerdo y res."

**S-P4-04 — OWL cooking method expansion: "pollo sudado"**:
- GIVEN user asks "¿pollo sudado tienen?"
- WHEN Phase 1 OWL exact finds nothing
- AND query expansion splits: "pollo" → ingredient, "sudado" → cooking method
- AND OWL runs: `?s :hasMainIngredient :Pollo` → "Pechuga a la plancha" (0.7), "Pechuga gratinada" (0.7)
- AND OWL runs: `?s :hasCookingMethod :Sudado` → "Bocachico criollo frito / sudado" (0.7)
- WHEN RRF fuses 4 signals + cross-encoder reranks
- AND Phase 3 Gate validates both Pechuga items and Bocachico exist → ✅ pass
- THEN response says "Pollo sudado exacto no tenemos. Pero tenemos **Pechuga a la plancha** (pollo a la plancha), **Pechuga gratinada** y también **Bocachico sudado** (pescado, preparado sudado). ¿Te llama alguna?"

**S-P4-05 — OWL exact match fast path: "pechuga a la plancha"**:
- GIVEN user asks "¿cuánto cuesta la pechuga a la plancha?"
- WHEN Phase 1 runs SPARQL: `SELECT ?amount WHERE { ?s :itemName "Pechuga a la plancha" . ?s :hasPriceOption ?po . ?po :hasAmount ?amount }`
- AND ontology returns `$13,500 (Corriente), $12,000 (mini)` — ground truth, <5ms
- THEN pipeline **short-circuits** Phase 2 and Phase 3 entirely
- AND response cites exact price: "Pechuga a la plancha: $13,500 (Corriente) / $12,000 (mini)"
- AND total latency <50ms for this query (no LLM call)

### Acceptance Criteria
- RAG recall@10 improves ≥15% over current single-pass dense (benchmark)
- ~~"What did I order last Tuesday?" returns correct episode within 2s~~ **⚠️ DEPRECATED** — EpisodicStore not fully implemented
- Cross-encoder ≤500ms (ONNX-optimized)
- **Zero menu hallucinations** (adversarial test with 20 invented dish names → all rejected by Ontology Validation Gate)
- **OWL exact match** short-circuits pipeline in <50ms for known items
- **"marrano" → lomo de cerdo**: OWL ingredient expansion returns correct related items (accuracy ≥0.9)
- **"pollo sudado" → pechuga + bocachico**: OWL method + ingredient expansion returns both correct signals
- **Non-existent item (e.g. "chuleta de cerdo")**: Ontology Gate rejects or penalizes, pipeline falls back to clarification
- **OntologyGateError** raised when ALL candidates rejected → user gets clarification response, not silence or hallucination
- All 360 existing tests pass

### Dependencies
- P1 (error hierarchy) for typed RAG errors + `OntologyGateError`
- P2 (MemoryHub) for entity embeddings
- P3 (checkpointing) for episode state saves
- **OWL infrastructure** — `OwlClient` + `menu.ttl` (YA EXISTE, se enriquece)
- `ontology_synonyms.json` (new data file)
- `sentence-transformers` (new dependency)
- `rank-bm25` or Whoosh (new dependency)
- ONNX runtime for cross-encoder optimization

### Non-Requirements
- No replacement of existing single-pass RAG (both paths coexist behind flag)
- No procedural memory (P5)
- No semantic cache (P5)

---

## Phase P5: Procedural Memory + Semantic Cache + Typo Tolerance

| Field | Value |
|-------|-------|
| **Capability** | Pattern learner (order correlations, user tendencies), embedding-based semantic cache, fuzzy menu matching |
| **Issues fixed** | 4 (latency via cache), 5 (typo fragility), 6 (procedural memory gap) |

### Requirements

| ID | Description | Strength |
|----|-------------|----------|
| FR-P5-01 | Procedural pattern learner tracks co-occurrence counts: "user ordered X + Y together N times". Threshold: min 3 co-occurrences before auto-suggest. | MUST |
| FR-P5-02 | Semantic cache stores `(query_embedding, response, timestamp, session_id)` in a ChromaDB collection. Returns cached response for queries with cosine similarity ≥ 0.92. | MUST |
| FR-P5-03 | Cache invalidation triggers: TTL expiry (5 min default), menu change event, order state change in same session. | MUST |
| FR-P5-04 | Fuzzy matcher applies Levenshtein distance ≤ 2 on known menu entity names BEFORE classification. Correction is logged and transparent to pipeline. | MUST |
| FR-P5-05 | Procedural patterns with confidence < 0.7 are logged as suggestions only, never auto-applied. | SHALL |
| FR-P5-06 | Feature flag `procedural_mode` with values `auto`, `rule_only`, `off`. Default: `rule_only` in P5. | MUST |

### Scenarios

**S-P5-01 — Typo correction**:
> **⚠️ DEPRECATED** — Fuzzy matcher (Levenshtein) was not implemented. Descoped per re-plan.
- GIVEN user types "epchuga"
- WHEN fuzzy matcher tests Levenshtein distance against menu entities
- AND "pechuga" matches at distance 1
- THEN the query is corrected to "pechuga" before classification
- AND user never sees a correction message — response treats it as "pechuga"

**S-P5-02 — Semantic cache hit**:
> **⚠️ DEPRECATED** — SemanticCache was not implemented. Descoped per re-plan.
- GIVEN user asks "¿cuál es el horario?" in session 1 (5s response, cached)
- WHEN same user asks "¿a qué hora abren?" in session 2
- AND embedding cosine similarity between queries ≥ 0.92
- THEN cached response returned in <500ms without LLM call
- AND cache hit is logged: `{"cache": "hit", "similarity": 0.94, "saved_ms": 4500}`

**S-P5-03 — Pattern below threshold**:
> **⚠️ DEPRECATED** — ProceduralStore (pattern learner) was not implemented. Descoped per re-plan.
- GIVEN user ordered "carne asada" + "frijoles" together in 2 past sessions (N=2)
- WHEN they order "carne asada" again
- THEN threshold (N≥3) not met → pattern is stored but NOT suggested
- AND response does NOT include "¿Quieres también frijoles?"

### Acceptance Criteria
- ~~"epchuga" → "pechuga" match in <50ms without LLM~~ **⚠️ DEPRECATED** — Fuzzy matcher not implemented
- ~~Semantic cache hits <500ms vs 5–10s uncached~~ **⚠️ DEPRECATED** — SemanticCache not implemented
- ~~Patterns with N<3 never auto-applied~~ **⚠️ DEPRECATED** — ProceduralStore not implemented
- `procedural_mode=off` disables ALL pattern-learning code paths
- All 360 existing tests pass

### Dependencies
- P2 (MemoryHub) for embedding-based cache lookup
- P4 (RAG v2) for cross-encoder and menu grounding
- Menu entity list from OWL ontology for fuzzy matching
- `numpy` (already transitive via ChromaDB)

### Non-Requirements
- No ML training pipeline — procedural memory is rule-based counting
- No distributed or shared cache
- No cross-user pattern learning

---

## Phase P6: Supervisor Pattern

| Field | Value |
|-------|-------|
| **Capability** | Coordinator delegates to specialist sub-pipelines, rule-based procedural fallback, guaranteed summarization |
| **Issues fixed** | 15 (architectural debt), fire-and-forget unreliability |

### Requirements

| ID | Description | Strength |
|----|-------------|----------|
| FR-P6-01 | Coordinator delegates to specialists: `classify_agent`, `retrieve_agent`, `reason_agent`, `respond_agent`. Each accepts `(context: TraceContext, input)` → `StageResult[T]`. | MUST |
| FR-P6-02 | `procedural_mode=rule_only` replaces the pattern learner (P5) with explicit if-then rules: "if address exists → infer delivery", "if past_orders contain X → prefer X". | MUST |
| FR-P6-03 | Summarization stage uses a completion guard: coordinator awaits a completion signal with configurable timeout (default 5s). On timeout, synchronous fallback summary is written immediately with turn data only (no LLM). | MUST |
| FR-P6-04 | Coordinator limits concurrent messages to N (default 5) via `asyncio.Semaphore`. | MUST |
| FR-P6-05 | Specialist agents are SEQUENTIAL (classify → retrieve → reason → respond), not parallel. Each agent's output feeds the next. | SHALL |
| FR-P6-06 | Each specialist agent writes its own checkpoint (P3 pattern) for granular crash recovery within the supervisor. | MUST |

### Scenarios

**S-P6-01 — Specialist delegation flow**:
- GIVEN user message "quiero ordenar pechuga para delivery"
- WHEN coordinator receives classified message
- THEN delegates to `classify_agent` → `retrieve_agent` (menu + user facts) → `reason_agent` (order logic) → `respond_agent`
- AND each passes `TraceContext` with updated spans
- AND final response includes delivery address inference + dish confirmation

**S-P6-02 — Guaranteed summarization**:
- GIVEN successful pipeline completion for message N
- WHEN summarization is launched with completion guard
- AND the LLM call times out after 5s
- THEN coordinator falls back to synchronous summary: `{turn: N, message: snippet, response: snippet, timestamp, error: "timeout"}`
- AND writes the fallback immediately — every turn produces a summary

**S-P6-03 — Concurrent message processing**:
- GIVEN the coordinator receives 8 concurrent messages from different users
- WHEN the semaphore limits to 5 concurrent processes
- THEN 3 messages wait in queue
- AND no message crashes or produces corrupted state
- AND all 8 complete successfully within bounded time

### Acceptance Criteria
- 5 concurrent messages processed without deadlock or race (stress test)
- `procedural_mode=rule_only` disables all P5 pattern-learning code paths
- 100% of turns produce a summary (sync or async) — zero missed turns
- Each specialist agent checkpoint is independently restorable
- All 360 existing tests pass

### Dependencies
- P1 (error hierarchy) for typed agent errors
- P2 (MemoryHub) for semantic context injection
- P3 (checkpointing) for per-agent save/restore
- P4 (episodic memory) for episode capture in summary
- P5 (procedural memory) for `rule_only` mode switch

### Non-Requirements
- No dynamic agent routing or discovery
- No external agent frameworks (LangGraph, CrewAI)
- Coordinator is a simple sequential loop — no DAG scheduler
- No parallel agent execution

---

## Cross-Cutting Constraints

| Constraint | Applies To |
|------------|------------|
| All 360 existing tests pass with zero regressions after each phase | P1–P6 |
| Coverage stays ≥70% (pytest-cov `fail_under=70`) | P1–P6 |
| Per-phase feature flags in `environment.py` — each phase independently disableable | P1–P6 |
| ChromaDB collections are the only new storage backend — no Postgres/Redis | P1–P6 |
| Old JSON persistence files remain readable — no destructive schema changes | P1–P6 |
| No UI changes (Gradio untouched) | P1–P6 |
| No external observability platforms — structured JSON log only | P1–P6 |
| New dependencies flagged in `requirements.txt` with version pins | P4 (`sentence-transformers`, `rank-bm25`) |

---

## Phase Dependency Graph

```
P1 (Foundation)
  └─► P2 (Semantic Memory)
  │     └─► P4 (Episodic + RAG v2)
  │     └─► P5 (Procedural + Cache)
  └─► P3 (Checkpointing + Obs)
        └─► P4
        └─► P5
              └─► P6 (Supervisor)
```

P2 and P3 are independent and MAY be implemented in parallel.
P4 depends on P2 + P3.
P5 depends on P2 + P4.
P6 depends on all prior phases.
