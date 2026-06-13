# Design: agent-memory-and-pipeline

## Technical Approach

Three-memory model (Semantic/Episodic/Procedural) unified under a `MemoryHub` class, orchestrated by a **`SkillOrchestrator`** that loads skills dynamically via progressive disclosure. Skills are independent modules (directory + `SKILL.md`) loaded on demand based on user intent. Feature-flagged per phase, ChromaDB + JSON only. `StageResult[T]` is retained and adapted as `SkillResult[T]`.

## Architecture Decisions

### Decision: Memory Hub as Facade, not monolithic god-class

| Option | Tradeoffs | Decision |
|--------|-----------|----------|
| Single `MemoryHub` class delegating to 3 internal stores | Clean API, single import point; still allows separate testing per store | ✅ Chosen |
| 3 independent services wired in assistant.py | More DI, more boilerplate in caller | Rejected |
| One class doing everything | Tight coupling, hard to test | Rejected |

`MemoryHub` owns 3 internal stores — `SemanticStore`, `EpisodicStore`, `ProceduralStore` — and exposes `store()`, `query()`, `recall()`.

### Decision: ChromaDB collection per memory type (3 collections)

| Option | Tradeoffs | Decision |
|--------|-----------|----------|
| 3 ChromaDB collections | 1 client, 3 handles — simple, separate metadata schemas | ✅ Chosen |
| Single collection with type tag | Cross-type pollution risk, harder to clear one type | Rejected |
| JSON-only (no vectors for semantic) | No similarity search for facts | Rejected |

Collections: `memory_semantic`, `memory_episodic`, `memory_cache` (semantic cache).

### Decision: Procedural memory as rule engine, NOT ML

| Option | Tradeoffs | Decision |
|--------|-----------|----------|
| Rule engine + confidence thresholds | Deterministic, testable, no deps | ✅ Chosen |
| Lightweight ML (scikit-learn) | Ops burden, harder to revert | Rejected |
| LLM-prompted pattern extraction | Non-deterministic, expensive per call | Rejected |

Rules: "entity X → entity Y correlation count > threshold", "user always → preference inference". Same Beta-Binomial approach as existing `UserPreferences`.

### Decision: Pipeline refactor keeps current StageResult[T] + adds coordinator loop

| Option | Tradeoffs | Decision |
|--------|-----------|----------|
| Keep `StageResult[T]`, add checkpoint mixin | Minimal diff, works with existing code | ✅ Chosen |
| Rewrite as state machine (transitions library) | More complexity, breaks existing patterns | Rejected |
| LangGraph-style graph | Overkill for 9 linear stages | Rejected |

### Decision: Typed exception hierarchy replacing `except Exception`

```
PipelineError (base)
├── StageExecutionError       # Stage itself failed
├── ValidationGateError       # Output failed schema check
├── CheckpointError           # Save/restore failed
├── MemoryHubError            # Any memory store failure
├── CacheError                # Semantic cache failure
└── OntologyGateError         # Ontology validation failed (all candidates rejected)
```

### Decision: RAG v2 with OWL ontology signal + RRF + cross-encoder

**4 signals fused via RRF**, not 3:

| Signal | Source | When it wins |
|--------|--------|-------------|
| **Dense** (ChromaDB) | Existing embedding index | Semantic similarity: "algo como carne pero más ligero" |
| **BM25** (`rank_bm25`) | Keyword index | Exact/partial term match: "pechuga plancha" |
| **Entity** (MemoryHub) | Semantic memory | User-specific facts: "lo que pedí la semana pasada" |
| **OWL/SPARQL** 🆕 | Ontología TTL + rdflib | **Deterministic ground truth**: "¿existe pollo sudado?", "¿qué proteínas hay?", "¿cuánto cuesta?" |

```
Dense + BM25 + Entity + OWL → RRF → Cross-encoder → [Ontology Validation Gate] → Top-5
```

All behind `rag_v2_enabled` flag. The OWL signal provides **deterministic scores** — exact ontology hit = 1.0, partial = 0.8, synonym/related = 0.7, no match = 0.0.

### Decision: Ontology enrichment with CookingMethod + Ingredient taxonomy

The existing `menu.ttl` models sections, items, prices, and options — but NOT cooking methods, main ingredients, or related terms. Enrich it:

```turtle
# Nuevas clases
:CookingMethod a owl:Class .
:Ingredient a owl:Class .

# Propiedades
:hasCookingMethod a owl:ObjectProperty .
:hasMainIngredient a owl:ObjectProperty .

# Instancias de método de cocción
:Sudado a :CookingMethod .
:Frito a :CookingMethod .
:APlancha a :CookingMethod .
:Gratinado a :CookingMethod .
:BBQ a :CookingMethod .
:Asado a :CookingMethod .

# Instancias de ingrediente principal
:Pollo a :Ingredient .
:Cerdo a :Ingredient .
:Res a :Ingredient .
:Pescado a :Ingredient .
:Verdura a :Ingredient .

# Relacionar items existentes
:Bocachico :hasCookingMethod :Sudado, :Frito ;
           :hasMainIngredient :Pescado .
:PechugaAPlancha :hasCookingMethod :APlancha ;
                 :hasMainIngredient :Pollo .
:PechugaGratinada :hasCookingMethod :Gratinado ;
                  :hasMainIngredient :Pollo .
:LomoCerdo :hasCookingMethod :Asado, :APlancha ;
            :hasMainIngredient :Cerdo .
:CarnesMixtas :hasMainIngredient :Res, :Cerdo .
```

Además, se agrega un **synonym/related-entity mapping** liviano (JSON, no TTL):

```json
{
  "marrano": { "related_ingredients": ["cerdo"], "items": ["lomo de cerdo asado a la plancha"] },
  "pollo": { "related_ingredients": ["pollo"], "items": ["pechuga a la plancha", "pechuga gratinada"] },
  "pescado": { "related_ingredients": ["pescado"], "items": ["bocachico criollo frito / sudado"] },
  "sudado": { "cooking_method": "sudado", "items": ["bocachico criollo frito / sudado"] }
}
```

Esto permite que la señal OWL responda: _"No hay pollo sudado exacto, pero hay **Pechuga a la plancha** (pollo → ingrediente) y **Bocachico sudado** (sudado → método de cocción)"_.

### Decision: Ontology validation gate after cross-encoder

A new `StageResult[T]` gate that validates every cross-encoder candidate against the OWL ontology BEFORE it reaches the response builder:

| Gate Outcome | Action | Example |
|-------------|--------|---------|
| ✅ Exact match in `menu.ttl` | Preserve confidence, no penalty | "Pechuga a la plancha" |
| 🟡 Semantic match (related ingredient, cooking method, section) | Boost confidence + tag `"related"` | "Lomo de cerdo" for query "marrano" |
| ❌ Not found in ontology | Penalize confidence × 0.3 OR remove from top-5 | "Chuleta de cerdo" inventado |

This is the **hallucination firewall** — any dish name that doesn't exist in the ontology gets flagged regardless of what the cross-encoder or LLM suggests.

`OntologyGateError` added to exception hierarchy for when the gate rejects ALL candidates (pipeline falls back to clarification: "No tenemos eso. ¿Te interesa algo de [menu summary]?").

### Decision: Semantic cache with cosine-similarity + WAL invalidation

Query embedding → cosine > 0.92 → return cached. On any write to memory/orders → invalidate affected cache keys. `cache_ttl_minutes` configurable.

---

### Decision: Skill-based architecture (Nivel A) replacing linear pipeline

| Option | Tradeoffs | Decision |
|--------|-----------|----------|
| **SkillOrchestrator** + `load_skill()` meta-tool | Modular, progressive disclosure, no context rot; skills as Python modules with SKILL.md | ✅ **Chosen** |
| Pipeline de 9 stages estáticos (actual) | Context rot garantizado, skills siempre cargadas sin uso, difícil de extender | Rejected |
| Agents framework externo (LangGraph, CrewAI) | Overkill, rompe simplicidad del proyecto, curva de aprendizaje | Rejected |

7 skills: `classify`, `menu-query`, `rag-retrieve`, `order-flow`, `response-build`, `memory-store`, `summarize`.

No skills: Input Guard, Session Prep, LLM Guard (framework), Checkpointing, TraceContext, Logging (infra), MemoryHub + Semantic Cache (infra que las skills usan).

El **ThoughtGenerator** actual no es skill ni stage — **es el orquestador mismo**. El orquestador piensa, decide qué skills cargar según el `intent` clasificado, delega la ejecución a la skill correspondiente, y recoge los resultados para armar la respuesta.

### Decision: Skill directory structure

```
skills/
  <skill-name>/
    SKILL.md          # Frontmatter (descubrimiento) + body (activación)
    __init__.py       # Punto de entrada Python (load, run, unload)
    scripts/          # Scripts deterministas (opcional, para Nivel B futuro)
    tests/            # Tests unitarios de la skill
```

SKILL.md frontmatter (YAML, ~50-100 tokens — Level 1: descubrimiento):
```yaml
name: menu-query
display: Consulta de Menú
trigger: "user pregunta por el menú, precios, ingredientes, métodos de cocción"
intents: [menu_query, price_check, ingredient_lookup]
deterministic: true
dependencies: [owl_client, ontology_synonyms]
```

Skill class pattern:
```python
# skills/<name>/__init__.py
class Skill:
    name: str
    def load(self, context: OrchestratorContext) -> None: ...
    async def run(self, input: SkillInput) -> SkillResult: ...
    def unload(self) -> None: ...
```

### Decision: Progressive disclosure en 3 niveles

| Level | Tokens | Qué expone | Cuándo |
|-------|--------|------------|--------|
| **L1 — Discovery** | ~50-100 | Frontmatter YAML (nombre, trigger, intents) | En el `skill_registry` que el orquestador consulta para decidir |
| **L2 — Activation** | ~1K-3K | SKILL.md completo (instrucciones, ejemplos, contratos) | Cuando el orquestador decide usar la skill |
| **L3 — Execution** | N/A | Ejecución del script/llamada Python | Cuando el orquestador invoca `skill.run(input)` |

El orquestador mantiene un `skill_registry` con todas las skills registradas (L1). Al clasificar un mensaje, decide qué skills activar (L2). La ejecución (L3) es directa — no se pasa contexto innecesario.

### Decision: StageResult[T] → SkillResult[T]

`StageResult[T]` se adapta: el campo `stage_name` pasa a ser `skill_name`, y se agrega `skill_version` desde el frontmatter. La interfaz `success/fail` se mantiene idéntica, al igual que el tipado Pydantic.

```python
class SkillResult(BaseModel, Generic[T]):
    success: bool
    skill_name: str
    skill_version: str
    value: T | None       # typed via Pydantic schema contract
    error: PipelineError | None
    metadata: dict        # trace_id, checkpoint_id, duration_ms
```

---

## Data Flow (Skill-Based)

```
User Message
  │
  ├── Framework ──────────────────────────────────────────────┐
  │   [Input Guard] → [Session Prep] → [LLM Guard]           │ Siempre
  │   (checkpoint, trace, validation)                         │
  │                                                            │
  ├── Skill: classify (Siempre, L2 Activation) ───────────────┤
  │   load_skill("classify") → run(message)                   │
  │   → {intent, topics, entities, confidence}                │
  │                                                            │
  ├── Orchestrator decide ─────────────────────────────────────┤
  │   Según intent + topics:                                   │
  │   • menu_query?      → load_skill("menu-query")           │
  │   • info_request?    → load_skill("rag-retrieve")         │  
  │   • order_intent?    → load_skill("order-flow")           │
  │   • multiple?        → carga las que correspondan         │
  │                                                            │
  ├── [Semantic Cache: lookup] ──hit?──→ return cached ───────┤
  │   (antes de cargar skills costosas)                        │
  │                                                            │
  ├── Skill Execution ─────────────────────────────────────────┤
  │   ┌─ menu-query ──────────────────────────────────┐       │
  │   │  Phase 1: OWL Exact Match (<5ms)              │       │
  │   │    SPARQL exact itemName? → hit? → return     │       │
  │   │  Phase 2: OWL Partial (solo si Phase 1 miss)  │       │
  │   │    • CONTAINS itemName                         │       │
  │   │    • hasCookingMethod                          │       │
  │   │    • hasMainIngredient + synonyms              │       │
  │   │  → Ontology Validation Gate                    │       │
  │   └────────────────────────────────────────────────┘       │
  │   ┌─ rag-retrieve ────────────────────────────────┐       │
  │   │  Dense (ChromaDB) + BM25 + Entity (MemoryHub) │       │
  │   │  → RRF → Cross-encoder → Top-5                │       │
  │   └────────────────────────────────────────────────┘       │
  │   ┌─ order-flow ──────────────────────────────────┐       │
  │   │  CRUD órdenes, validación items, confirmación │       │
  │   │  → OrderOrchestrator + ActionPlanner          │       │
  │   └────────────────────────────────────────────────┘       │
  │   (skills se ejecutan secuencial o paralelo según           │
  │    dependencias; checkpoint después de cada skill)          │
  │                                                            │
  ├── Skill: response-build (Siempre) ─────────────────────────┤
  │   load_skill("response-build") → run(context)              │
  │   → assistant_response (str)                               │
  │                                                            │
  ├── Skill: memory-store (Siempre, post-respuesta) ───────────┤
  │   load_skill("memory-store") → run(turn)                   │
  │   → EpisodicStore.append_turn() + SemanticStore.extract()  │
  │                                                            │
  ├── Framework ───────────────────────────────────────────────┤
  │   Logging + Trace (structured JSON event log)              │
  │   Skill: summarize (fire-and-forget con completion guard)  │
  └────────────────────────────────────────────────────────────┘
```

## File Changes

### New Files

| File | Description |
|------|-------------|
| `src/core/memory/domain/memory_hub.py` | `MemoryHub` facade — `store()`, `query()`, `recall()` |
| `src/core/memory/domain/semantic_store.py` | Semantic memory store — entity CRUD, ChromaDB collection |
| `src/core/memory/domain/episodic_store.py` | Episode capture, ChromaDB + JSON time index |
| `src/core/memory/domain/procedural_store.py` | Rule engine for pattern learning, JSON persistence |
| `src/core/memory/domain/models_memory.py` | Entity, Episode, Pattern Pydantic models |
| `src/core/memory/infrastructure/chroma_memory_repository.py` | ChromaDB adapter for memory collections |
| `src/core/agent/exceptions.py` | Typed exception hierarchy |
| `src/core/agent/checkpoint.py` | `CheckpointManager` — save/restore per stage |
| `src/core/agent/validation_gates.py` | Pydantic-based stage output validators |
| `src/core/agent/trace_context.py` | `TraceContext` with `contextvars`, `@span` decorator |
| `src/core/agent/orchestrator.py` | **`SkillOrchestrator`** — `load_skill()`, skill lifecycle, registry, decision engine |
| `src/core/agent/skill_registry.py` | Skill registry — frontmatter index, L1 discovery, path resolution |
| `src/core/agent/skill_base.py` | `BaseSkill` abstract class — `load/run/unload` interface + versioning |
| `src/core/agent/exceptions.py` | Typed exception hierarchy |
| `src/core/agent/checkpoint.py` | `CheckpointManager` — save/restore per skill execution |
| `src/core/agent/validation_gates.py` | Pydantic-based stage output validators |
| `src/core/agent/trace_context.py` | `TraceContext` with `contextvars`, `@span` decorator |
| `src/core/memory/domain/memory_hub.py` | `MemoryHub` facade — `store()`, `query()`, `recall()` |
| `src/core/memory/domain/semantic_store.py` | Semantic memory store — entity CRUD, ChromaDB collection |
| `src/core/memory/domain/episodic_store.py` | Episode capture, ChromaDB + JSON time index |
| `src/core/memory/domain/procedural_store.py` | Rule engine for pattern learning, JSON persistence |
| `src/core/memory/domain/models_memory.py` | Entity, Episode, Pattern Pydantic models |
| `src/core/memory/infrastructure/chroma_memory_repository.py` | ChromaDB adapter for memory collections |
| `src/core/extractor/bm25_retriever.py` | BM25 retriever using `rank_bm25` |
| `src/core/extractor/entity_retriever.py` | Entity matcher against semantic memory |
| `src/core/extractor/owl_signal.py` | **OWL/SPARQL signal** — exact match, partial match, ingredient/cooking-method, synonym expansion |
| `src/core/extractor/ontology_validation_gate.py` | **Ontology validation gate** — validates candidates against `menu.ttl` |
| `src/core/extractor/ontology_synonyms.py` | Synonym mapping (JSON) for OWL query expansion |
| `src/core/extractor/rrf_fuser.py` | RRF score fusion (dense + BM25 + entity + OWL scores) |
| `src/core/extractor/cross_encoder_reranker.py` | Cross-encoder reranking via sentence-transformers |
| `src/core/cache/semantic_cache.py` | `SemanticCache` — embedding lookup + TTL invalidation |
| `skills/classify/__init__.py` | `classify` skill — intent + topic classification |
| `skills/classify/SKILL.md` | Frontmatter + activación para classificar |
| `skills/menu-query/__init__.py` | `menu-query` skill — OWL/SPARQL determinista |
| `skills/menu-query/SKILL.md` | Frontmatter + activación para consulta de menú |
| `skills/rag-retrieve/__init__.py` | `rag-retrieve` skill — dense + BM25 + entity → RRF → cross-encoder |
| `skills/rag-retrieve/SKILL.md` | Frontmatter + activación para recuperación |
| `skills/order-flow/__init__.py` | `order-flow` skill — CRUD de órdenes |
| `skills/order-flow/SKILL.md` | Frontmatter + activación para flujo de pedido |
| `skills/response-build/__init__.py` | `response-build` skill — armado de respuesta final |
| `skills/response-build/SKILL.md` | Frontmatter + activación para respuesta |
| `skills/memory-store/__init__.py` | `memory-store` skill — persistencia + extracción de facts |
| `skills/memory-store/SKILL.md` | Frontmatter + activación para memoria |
| `skills/summarize/__init__.py` | `summarize` skill — resumen de sesión fire-and-forget |
| `skills/summarize/SKILL.md` | Frontmatter + activación para resumen |

### Modified Files

| File | Change |
|------|--------|
| `src/core/assistant.py` | Wire `SkillOrchestrator`, `MemoryHub`, `CheckpointManager`; reemplazar pipeline fijo con orchestration loop |
| `src/core/agent/stage_result.py` | Add `SkillResult[T]` with `skill_name`, `skill_version` fields |
| `src/core/memory/application/context_summarizer.py` | Add entity extraction callback to `MemoryHub.semantic.extract()` |
| `src/core/memory/domain/models.py` | Add optional `extracted_entities` field |
| `src/core/extractor/composite_retriever.py` | Refactor: split RAG logic into `menu-query` + `rag-retrieve` skills; keep as factory/dispatcher |
| `src/core/extractor/retriever_interface.py` | Add `retrieve_v2()` method with fused scores |
| `data/ontology/menu.ttl` | Enrich with `CookingMethod`, `Ingredient`, `hasCookingMethod`, `hasMainIngredient` — link existing items |
| `data/ontology/ontology_synonyms.json` | **New data file** — synonym/related-entity mapping for query expansion |
| `src/config/environment.py` | Add feature flags for each phase + orchestrator flags |
| `src/core/order/application/orchestrator.py` | Add checkpoint-aware state persistence |
| `src/core/user/preferences.py` | Merge path — sync to `MemoryHub.semantic` on save |
| `src/core/agent/stage_result.py` | Add `SkillResult[T]` + `metadata` field for checkpoint_id, trace_id |

## Interfaces / Contracts

### MemoryHub (domain layer)

```python
class MemoryHub:
    semantic: SemanticStore
    episodic: EpisodicStore
    procedural: ProceduralStore

    async def store(self, memory_type: str, data: dict) -> str: ...
    async def query(self, memory_type: str, query: str, **filters) -> list[dict]: ...
    async def recall(self, context: RecallContext) -> RecallResult: ...
```

### SemanticStore

```python
class SemanticStore:
    async def store_entity(self, entity: Entity) -> str: ...
    async def query_by_entity(self, entity_type: str, value: str) -> list[Entity]: ...
    async def query_by_semantic(self, text: str, top_k: int = 5) -> list[Entity]: ...
    async def query_by_keyword(self, keyword: str) -> list[Entity]: ...
    async def extract_from_turn(self, turn: ConversationTurn) -> list[Entity]: ...
```

Entity schema (Pydantic):
```python
class Entity(BaseModel):
    entity_id: str           # UUID
    entity_type: str         # "user_preference" | "dietary_restriction" | "address" | "known_dish" | "payment_method"
    value: str               # "carne bien asada"
    user_id: str
    confidence: float        # 0.0–1.0 (from Beta-Binomial)
    source_turns: list[int]  # provenance
    embedding: list[float]   # vector
    metadata: dict           # any additional context
    created_at: datetime
    updated_at: datetime
```

### EpisodicStore

```python
class EpisodicStore:
    async def start_episode(self, session_id: str, user_id: str) -> str: ...
    async def append_turn(self, episode_id: str, turn: ConversationTurn) -> None: ...
    async def close_episode(self, episode_id: str, outcome: str) -> None: ...
    async def query_by_time(self, user_id: str, start: datetime, end: datetime) -> list[Episode]: ...
    async def query_by_topic(self, user_id: str, topic: str) -> list[Episode]: ...
    async def query_by_entity(self, user_id: str, entity_value: str) -> list[Episode]: ...
    async def query_by_outcome(self, user_id: str, outcome: str) -> list[Episode]: ...
```

Episode schema:
```python
class Episode(BaseModel):
    episode_id: str
    session_id: str
    user_id: str
    started_at: datetime
    ended_at: Optional[datetime]
    outcome: Optional[str]    # "completed_order" | "abandoned" | "clarified" | "information_only"
    turn_count: int
    entities_involved: list[str]  # entity_ids
    summary: Optional[str]
```

### CheckpointManager

```python
@dataclass
class Checkpoint:
    stage_name: str
    stage_index: int
    trace_id: str
    input_data: dict
    output_data: dict
    created_at: datetime
    validated: bool

class CheckpointManager:
    async def save(self, stage: str, data: dict) -> None: ...
    async def load_latest(self, session_id: str) -> Optional[Checkpoint]: ...
    async def clear(self, session_id: str) -> None: ...
    def checkpoint_path(self, session_id: str) -> Path: ...  # data/checkpoints/{session_id}.json
```

### TraceContext

```python
from contextvars import ContextVar

trace_id_var: ContextVar[str] = ContextVar("trace_id")
span_stack_var: ContextVar[list[str]] = ContextVar("span_stack", default=[])

@contextmanager
def span(name: str): ...  # push/pop with timing, emit structured event log

def get_trace_id() -> str: ...
def new_trace_id() -> str: ...
```

### Exception Hierarchy

```python
class PipelineError(Exception): pass
class StageExecutionError(PipelineError): pass       # stage_name, original_exception
class ValidationGateError(PipelineError): pass       # stage_name, violations: list[str]
class CheckpointError(PipelineError): pass            # operation: "save"|"load", path
class MemoryHubError(PipelineError): pass             # memory_type, operation
class CacheError(PipelineError): pass                 # cache_key, operation
```

### RAG v2 Fusion Formula

```
RRF(d, q) = Σ( 1 / (k + rank_i(d, q)) )  for each retriever i

k = 60 (standard)
Final score = RRF_dense + RRF_bm25 + RRF_entity + RRF_owl
Top 20 → cross-encoder → reranked top 5-10 → [Ontology Validation Gate]
```

**OWL signal scoring**: Unlike dense/BM25/entity which assign ranks, OWL assigns deterministic scores per candidate:

| Match type | Score | Query example |
|-----------|-------|--------------|
| Exact itemName match | 1.0 | `SELECT ?item WHERE { ?s :itemName "Bocachico criollo frito / sudado" }` |
| Partial itemName (CONTAINS) | 0.8 | `FILTER(CONTAINS(LCASE(?item), "pechuga"))` |
| Ingredient match (hasMainIngredient) | 0.7 | `?s :hasMainIngredient :Cerdo .` for query "marrano" |
| Cooking method match (hasCookingMethod) | 0.7 | `?s :hasCookingMethod :Sudado .` for query "sudado" |
| Synonym expansion match | 0.6 | "marrano" → synonym.json → `:Cerdo` → LomoCerdo |
| No ontology match | 0.0 | Item doesn't exist in menu.ttl → grounds hallucination |

The OWL signal feeds its score into RRF as if it were a rank position: `RRF_owl = 1 / (k + (max_rank - score * max_rank))`. This gives deterministic items a strong boost while allowing semantic signals to contribute nuance.

### Semantic Cache

```python
class SemanticCache:
    async def lookup(self, query: str, threshold: float = 0.92) -> Optional[CacheEntry]: ...
    async def store(self, query: str, response: str, metadata: dict) -> None: ...
    async def invalidate(self, pattern: str = "*") -> int: ...
    # Collection: memory_cache in ChromaDB
    # Invalidation: on order write, on memory write — mark stale, lazy cleanup
```

### OWL/SPARQL Signal

```python
class OwlSignal:
    """
    OWL/SPARQL signal for RRF fusion.
    Provides deterministic scores for menu items against the ontology.
    """

    async def score_candidates(
        self, query: str, candidates: list[str]
    ) -> dict[str, OwlMatch]:
        """
        Score each candidate item name against the ontology.

        Returns dict mapping item_name -> OwlMatch with:
          match_type: "exact" | "partial" | "ingredient" | "cooking_method" | "synonym" | "none"
          score: float 0.0–1.0
          evidence: str (SPARQL query or synonym that produced the match)
        """
        ...

    async def expand_query(self, query: str) -> QueryExpansion:
        """
        Expand raw user query with ontology terms.
        1. Extract tokens from query
        2. Check ontology_synonyms.json for related terms
        3. Build SPARQL queries for: exact itemName, CONTAINS, hasMainIngredient, hasCookingMethod

        Returns QueryExpansion with:
          original_tokens: list[str]
          expanded_terms: list[ExpandedTerm]  # { term, match_type, sparql }
        """
        ...

    async def validate_candidates(
        self, candidates: list[str], threshold: float = 0.3
    ) -> ValidationResult:
        """
        Ontology validation gate — determines if candidates exist.
        Returns ValidationResult with pass/flagged/rejected lists.
        Raises OntologyGateError if ALL candidates rejected.
        """
        ...
```

### Ontology Synonyms (data/ontology/ontology_synonyms.json)

```json
{
  "term": {
    "related_ingredients": ["ingredient1", "ingredient2"],
    "items": ["exact item name from menu.ttl"],
    "cooking_method": "method_name",
    "section": "menu section name"
  }
}
```

### Ontology Validation Gate

```python
class OntologyValidationGate:
    """
    Post-cross-encoder gate that validates each candidate against menu.ttl.
    
    Outcomes:
      - EXACT: itemName matches ontology → preserve confidence
      - RELATED: semantic match (ingredient, method, section) → tag "related", boost confidence
      - REJECTED: not in ontology → penalize confidence × 0.3 or remove from top-5
      - ALL_REJECTED: raise OntologyGateError → pipeline clarification fallback
    """

    async def validate(
        self, ranked_items: list[RankedItem], owl_signal: OwlSignal
    ) -> list[RankedItem]:
        ...
```

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Unit | `SemanticStore.store_entity/query_by_semantic` | Mock ChromaDB, assert entity roundtrip |
| Unit | `EpisodicStore` episode lifecycle | In-memory episode list mock |
| Unit | `ProceduralStore` rules | Known patterns → assert output, edge cases |
| Unit | `CheckpointManager.save/load/clear` | Temp JSON files, assert data fidelity |
| Unit | `ValidationGates` | Known good/bad stage outputs |
| Unit | `TraceContext.span` | Mock time, assert event log entries |
| Unit | `StageResult[T]` typed errors | Assert exception type on failure paths |
| Unit | `SemanticCache.lookup/store/invalidate` | Mock embeddings, assert cache hit/miss |
| Unit | `RRFFuser` (4-signal) | Known rank positions → assert fused scores with OWL deterministic signal |
| Unit | `OWL Signal — exact match` | Known item name → assert score = 1.0 |
| Unit | `OWL Signal — partial match` | Substring "pechuga" → assert score = 0.8 with known items |
| Unit | `OWL Signal — ingredient/cooking method` | "sudado" → assert `:hasCookingMethod` returns 0.7 items |
| Unit | `OWL Signal — synonym expansion` | "marrano" → synonym.json → assert `:Cerdo` items found at 0.6 |
| Unit | `OWL Signal — non-existent item` | "pollo guisado" → assert score = 0.0 (hallucination prevented) |
| Unit | `Ontology Validation Gate — exact` | Known item → assert passes, confidence unchanged |
| Unit | `Ontology Validation Gate — semantic` | Related item → assert tagged "related", confidence boosted |
| Unit | `Ontology Validation Gate — invented` | "chuleta de cerdo" → assert penalized or removed from top-5 |
| Unit | `Ontology Validation Gate — all rejected` | Only invented items → assert `OntologyGateError` raised, fallback to clarification |
| Unit | `SkillRegistry` — index, discovery, frontmatter parse | Assert L1 metadata extraction, path resolution |
| Unit | `BaseSkill.load/run/unload` lifecycle | Mock skill, assert lifecycle events |
| Unit | `SkillOrchestrator.decide_skills(intent)` | Known intents → assert skill list |
| Unit | `SkillResult[T]` — success/fail/merge | Assert typed success, error propagation, multi-skill merge |
| Integration | `MemoryHub.store/query/recall` | Real ChromaDB instance (test collection), assert cross-store recall |
| Integration | `SkillOrchestrator` with 2 real skills | Load `classify` + `response-build`, assert sequential execution + checkpoint |
| Integration | RAG v2 pipeline (BM25 → OWL → RRF → cross-encoder → gate) | Real menu.ttl + BM25 index + sample docs, assert ground-truth items ranked above hallucinated |
| Integration | Skill loading from `skills/` directory | File-based registry → assert load by name, version check |
| E2E | `process_message()` with skills enabled | Full orchestration, assert entity stored, episode closed, skills loaded/unloaded |
| Regression | All 360 existing tests pass | `pytest` with `fail_under=70` coverage |

## Migration / Rollout

| Phase | Flag | Files | Revert |
|-------|------|-------|--------|
| **P1** | `pipeline_validation_enabled` | exceptions.py, validation_gates.py, stage_result.py | Flag off = old error handling |
| **P2** | `skill_framework_enabled` | orchestrator.py, skill_registry.py, skill_base.py, skills/*/SKILL.md | Flag off = vuelve a assistant.py secuencial |
| **P3** | `checkpointing_enabled` | checkpoint.py, trace_context.py | Flag off + `data/checkpoints/` deleted |
| **P4** | `semantic_memory_enabled` | memory_hub.py, semantic_store.py, models_memory.py, chroma_memory_repository.py | Flag off + drop `memory_semantic` collection |
| **P5** | `rag_v2_enabled` | bm25_retriever.py, entity_retriever.py, owl_signal.py, rrf_fuser.py, cross_encoder_reranker.py, skills/menu-query/, skills/rag-retrieve/ | Flag off = uses existing `CompositeRetriever` |
| **P6** | `skills_enabled` | skills/order-flow/, skills/response-build/, skills/memory-store/, skills/summarize/, skills/classify/ | Flag off = assistant.py sin skills |

No schema changes to existing JSON persistence. Old `data/summaries/` continue working. Memory writes to separate ChromaDB collections — drop collection to reset.

## Dependencies (new)

- `rank_bm25` — BM25 retrieval
- `sentence-transformers` — cross-encoder reranking (`cross-encoder/ms-marco-MiniLM-L-6-v2`)
- `numpy` (transitive via ChromaDB) — RRF math
- `rdflib` (YA instalado, usado por `OwlClient`) — SPARQL queries contra menu.ttl
- `Ontology enrichment` — update `data/ontology/menu.ttl` with `CookingMethod` / `Ingredient` classes (no new deps, same file format)

## Open Questions

- [ ] Cross-encoder model download size (~400MB) — bundle or download on first use?
- [ ] BM25 index rebuild strategy — per-write or periodic batch?
- [ ] Semantic cache TTL default — 30min? 1hr? Per-query-type TTL?
- [ ] Procedural rule confidence threshold — start at 0.8? Tune from data?
- [ ] ChromaDB collection limit before archiving — 10K docs? Archive to JSON + clear collection?
- [ ] **OWL enrichment scope** — ¿cuántos `CookingMethod` e `Ingredient` vale la pena modelar? Solo los que aparecen en el menú actual, o预留 para expansión futura?
- [ ] **OWL synonym mapping** — ¿mantenemos `ontology_synonyms.json` manual o generamos automático desde embeddings de ingredientes?
- [ ] **OWL exact match short-circuit** — ¿debería también evitar el LLM completo (no solo RAG) cuando la query del user es unambiguousamente sobre un item del menú?
- [ ] **Skill hot-reload** — ¿recargar SKILL.md sin reiniciar el proceso? ¿File watcher?
- [ ] **Skill ordering** — ¿`response-build` y `memory-store` se ejecutan en paralelo o secuenciales?
- [ ] **`summarize` como skill separada** — ¿o debería integarse en `memory-store` para evitar latencia extra?
- [ ] **Skill versioning** — ¿frontmatter `version:` semver? ¿Conflicto si dos skills requieren versiones distintas de MemoryHub?
