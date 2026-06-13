# Proposal: agent-memory-and-pipeline

## Intent

Conversation log audit across 35 files reveals **15 critical issues**:

| Severity | Issue | Impact |
|----------|-------|--------|
| Critical | Null crisis — all fields null, `success:true`, no error logged | Silent data corruption |
| Critical | Empty response — `assistant_response:""` while orders created internally | User gets silence |
| Critical | Menu hallucinations — invents "chuleta de cerdo", "pollo guisado" | Trust erosion |
| High | Latency 40–79s per message | Abandonment |
| High | No semantic/episodic/procedural memory | Lost cross-session knowledge |
| High | No checkpointing — crash at Stage 6 loses Stages 1–5 | Waste |
| High | No validation gates — bad data propagates 4 stages before manifesting | Debug hell |
| High | Errors always swallowed — `except Exception: continue` | Masked failures |
| High | Hardcoded `service_type="delivery"` even when user never said delivery | Wrong orders |
| Med | Single-pass RAG (dense only, no reranking) | Low precision |
| Med | No trace_id propagation, no spans | Can't debug latency |
| Med | Typo fragility — "epchuga" → classified literally, no fuzzy matching | User frustration |
| Med | Fire-and-forget summarization — no completion guarantee | Lost context |
| Low | Summarization is rolling text only — no fact extraction | No structured memory |

Fix: **3-memory persistence model** as the core, with pipeline improvements wrapping it.

## Scope

### In Scope
- **Semantic memory**: User facts (preferences, address, dietary restrictions, known dishes) as structured entities with vector search via ChromaDB
- **Episodic memory**: Complete conversation episodes with timestamps, context, outcomes — queryable by time range, topic, entity
- **Procedural memory**: Learned patterns — "when user orders X they tend to also want Y", "this user always gets delivery"
- **Pipeline checkpointing**: Save state after each stage, resume from last checkpoint on crash
- **Validation gates**: Typed contracts between stages (`StageResult[T]` pattern) with schema validation
- **Error surfacing**: Replace `except Exception: continue` with typed error hierarchy, propagate to logging
- **RAG reranking**: Dense + BM25 + entity matching → RRF → cross-encoder
- **Observability**: `trace_id` propagation, span timing, structured event log
- **Semantic cache**: Cache responses by semantic similarity (embedding + threshold)
- **Fix hardcoded service_type**: Derive from user preference or clarify

### Out of Scope
- UI changes (Gradio, web, mobile)
- Payment gateway integration
- Multi-language support beyond current Spanish/English
- External observability platforms (Langfuse, OpenTelemetry collectors) — structured JSON log only
- Real-time streaming responses
- Agent-to-agent communication protocols
- Performance tuning beyond what comes naturally from the architecture changes

## Capabilities

### New Capabilities
- `semantic-memory`: User fact extraction, structured entity storage, vector+keyword retrieval
- `episodic-memory`: Conversation episode capture, time-range/topic/entity query
- `procedural-memory`: Pattern learning from past interactions, preference inference
- `pipeline-checkpointing`: Per-stage state persistence with crash resume
- `validation-gates`: Inter-stage contract validation with typed errors
- `rag-reranking`: Multi-signal retrieval (dense + BM25 + entity) with RRF fusion + cross-encoder
- `observability`: Trace_id propagation, span timing, structured event emission
- `semantic-cache`: Embedding-based response cache with invalidation
- `error-hierarchy`: Typed exception tree replacing bare `except Exception`

### Modified Capabilities
- `order-flow-tracker`: Add checkpoint-aware field state save/restore
- `user-preferences`: Merge with semantic memory entities (migration path)

## Approach

```
Core: 3-Memory Model (ChromaDB + JSON)
        │
  ┌─────┼─────┐
  │     │     │
Sem  Epis  Proc   ←── Memory Hub (unified query API)
               
Pipeline (refactored):
  Stage 1-9  →  [Checkpoint]  →  [Validate]  →  Next Stage
       ↑              ↑               ↑
  trace_id       save_state      StageResult[T]
       
RAG v2:
  User Query  →  Dense  ─┐
               →  BM25   ─┤→  RRF  →  Cross-Encoder  →  Ranked Results
               →  Entity ─┘
```

**Memory Hub**: Single `MemoryHub` class providing `store()` / `query()` / `recall()` across all three memory types, backed by ChromaDB collections + JSON indices.

**Pipeline refactor**: Wrap each stage in checkpoint/validate/gate pattern. `process_message()` orchestrates stages via a coordinator loop, not hardcoded sequential calls.

**Observability layer**: Decorator-based span timing + event emission. Thread-safe `TraceContext` propagated via `contextvars`.

## Phases

| Phase | Deliverables | Issues Fixed |
|-------|-------------|-------------|
| **P1: Foundation** | Error hierarchy (`StageResult[T]`, typed exceptions, error propagation), Validation gates (Pydantic schemas per stage contract), Fix null/empty response crisis, Fix hardcoded `service_type` | 1, 2, 7, 8, 13, 14 |
| **P2: Semantic Memory** | `MemoryHub` base, Semantic collection (user facts, preferences, dietary), Extraction pipeline from conversation turns, Entity-aware query API, Merge with existing `UserPreferences` | 6 (semantic), 10 |
| **P3: Checkpointing + Obs** | Per-stage checkpoint save/restore, Resume-from-crash logic, `trace_id` + span context propagation, Structured event log, Latency breakdown reporting | 9, 12 |
| **P4: Episodic + RAG v2** | Episode capture (turn groups with timestamps/outcomes), Query by time/topic/entity, RAG reranking (dense + BM25 + entity → RRF → cross-encoder), Fix menu hallucinations via entity grounding | 3, 6 (episodic), 11 |
| **P5: Procedural + Cache** | Pattern learner (order correlations, user tendencies), Preference inference engine, Semantic cache (embedding + threshold), Typo tolerance (fuzzy matching on menu entities) | 4, 6 (procedural), 5 (latency via cache) |
| **P6: Supervisor Pattern** | Orchestrator delegates to specialist agents (classify → retrieve → reason → respond), Rollback procedural memory to rule-based triggers, Fire-and-forget → guaranteed summarization | 15, architectural |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Latency increases before it decreases (extra memory writes, cross-encoder pass) | High | Feature flags per phase; benchmark before/after each phase |
| Memory writes race with pipeline — stale reads | Med | Write-ahead log + read-your-writes consistency per session |
| ChromaDB scalability — single-node, no sharding | Med | Keep collections small (<10K docs); archive to JSON on threshold |
| Cross-encoder adds 200–500ms per RAG call | Med | Cache common queries; keep reranking behind feature flag |
| Pipeline coordinator complexity overtakes current linear flow | Med | Keep coordinator loop simple; avoid async orchestration frameworks |
| Procedural memory produces bad patterns | Low | Human-in-loop review; confidence threshold before auto-apply |

## Rollback Plan

1. Per-phase feature flags in `environment.py` — each phase independently disableable
2. `MemoryHub` writes to separate ChromaDB collections — drop collection to reset
3. No schema changes to existing JSON persistence — old files remain readable
4. Postgres/Redis is NOT introduced — ChromaDB + JSON only, easy to revert

## Dependencies

- ChromaDB (already installed) — verify version ≥0.6.0 for collection metadata API
- `sentence-transformers` (for cross-encoder reranking) — new dependency
- `numpy` (for RRF score fusion) — already transitive via ChromaDB
- `contextvars` (Python 3.13 stdlib) — no install needed

## Success Criteria

- [ ] **P1**: Zero silent failures — every pipeline error produces a typed exception + structured log entry
- [ ] **P1**: Null crisis eliminated — `assistant_response` is never empty when `success=true`
- [ ] **P2**: `MemoryHub.store(entity)` and `MemoryHub.query("lechuga")` return semantically matched facts
- [ ] **P2**: User preference "carne bien asada" persists across sessions and surfaces in response
- [ ] **P3**: Pipeline crash at Stage 4 resumes from Stage 4 checkpoint without redoing Stages 1–3
- [ ] **P3**: Every message log includes `trace_id` with per-stage span timing
- [ ] **P4**: "What did I order last Tuesday?" returns correct episode — within 2s
- [ ] **P4**: RAG recall@10 improves by ≥15% over current single-pass dense
- [ ] **P5**: "epchuga" returns "lechuga" without LLM correction prompt
- [ ] **P5**: Semantic cache hits return in <500ms vs 5–10s uncached
- [ ] **P6**: Coordinator loop processes 5 concurrent messages without deadlock or race
- [ ] All 360 existing tests pass after each phase with zero regressions
- [ ] Coverage stays ≥70% (pytest-cov `fail_under=70`)
