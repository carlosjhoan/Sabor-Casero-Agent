# Design: OWL Menu Retrieval

## Technical Approach

Replace ChromaDB vector search for `menu.md` with a deterministic OWL ontology + SPARQL pipeline. A `CompositeRetriever` wraps two inner retrievers: `OwlRetriever` (routes `menu.md` → SPARQL against `menu.ttl`) and `HybridRetriever` (unchanged, serves non-menu docs from ChromaDB). Factory selects the composite when `retriever_type == "owl"`.

```
User query → Pipeline → group_by_doc = {"menu.md": [...], "service_info.txt": [...]}
                            │
                    CompositeRetriever
                      ├── menu.md ──→ OwlRetriever ──→ menu.ttl (rdflib/SPARQL)
                      └── other ───→ HybridRetriever ─→ ChromaDB (unchanged)
```

## Architecture Decisions

### Decision: Composite over Monolithic

| Option | Tradeoff |
|--------|----------|
| Modify `HybridRetriever` to special-case menu.md | Tight coupling; Mutates stable code |
| Pure `OwlRetriever` with fallback injection | OwlRetriever knows about ChromaDB — leaks abstraction |
| **CompositeRetriever routing by doc_name** | Zero changes to existing retrievers; single responsibility |

**Chosen**: CompositeRetriever. Each retriever is pure — `OwlRetriever` errors on non-menu docs, `HybridRetriever` stays untouched.

### Decision: Static Ontology File

| Option | Tradeoff |
|--------|----------|
| Generate `menu.ttl` at runtime from menu.md | Adds startup latency; menu rarely changes |
| **Commit `menu.ttl` to repo, ingest script as tool** | Deterministic; one-shot generation; git-tracked |
| Dynamic SPARQL endpoint | Overkill for ~50 triples |

**Chosen**: Committed `data/ontology/menu.ttl` + `scripts/ingest_menu_to_owl.py` for regeneration.

### Decision: Query Routing in OwlRetriever

The `OwlRetriever` inspects `detail.segment` (user query text) and matches against keyword patterns to select a SPARQL template. This avoids LLM overhead for query classification.

| Query Pattern | SPARQL Template |
|--------------|-----------------|
| `menu\|hoy\|qué hay` | Full menu (all sections + items) |
| `sopa\|entrada` | Items in `Sopa` section |
| `principio\|fuerte` | Items in `Principio` section |
| `acompañamiento` | Items in `Acompañamientos` section |
| `proteína\|carne\|pollo\|pescado` | Items in `Proteínas` section |
| `precio\|cuánto\|vale\|cuesta` | Price query (item + size variants) |
| `opcion\|opción\|variante` | OPTION sub-variants |
| Default | Full menu summary |

## Data Flow

1. `assistant._stage_rag()` calls `self.extractor.retrieve(group_by_doc)`
2. `CompositeRetriever.retrieve()` splits `group_by_doc` by key:
   - `"menu.md"` → `OwlRetriever.retrieve({"menu.md": details})`
   - Everything else → `HybridRetriever.retrieve(other)`
3. `OwlRetriever` loads `menu.ttl` via `OwlClient` (lazy singleton on first call)
4. For each `Detail`, matches `detail.segment` to a SPARQL template
5. Executes SPARQL via rdflib `GRAPH.query()`, formats result into `detail.info_extracted`
6. Both retrievers return `List[Detail]` → merged → returned to pipeline

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `data/ontology/menu.ttl` | Create | Turtle ontology modeling menu sections, items, prices, options |
| `src/infrastructure/owl_client.py` | Create | rdflib wrapper: loads `menu.ttl`, exposes typed SPARQL query methods |
| `src/core/extractor/owl_retriever.py` | Create | Implements `RetrieverInterface`; routes segment text → SPARQL |
| `src/core/extractor/composite_retriever.py` | Create | Routes by `doc_name`: menu.md → Owl, other → Hybrid |
| `src/core/extractor/retriever_factory.py` | Modify | Add `"owl"` case → returns `CompositeRetriever(owl, hybrid)` |
| `src/config/environment.py` | Modify | Add `owl_ontology_path: str = "data/ontology/menu.ttl"` |
| `scripts/ingest_menu_to_owl.py` | Create | One-shot parser: `menu.md` → `menu.ttl` |

## Interfaces / Contracts

```python
class OwlClient:
    def __init__(self, ontology_path: str)
    def get_menu_summary(self) -> str
    def get_section_items(self, section_name: str) -> str
    def get_item_price(self, item_name: str) -> str
    def get_item_options(self, item_name: str) -> str
    def query_deterministic(self, sparql: str) -> list[dict]

class OwlRetriever(RetrieverInterface):
    def __init__(self, owl_client: OwlClient | None = None)
    async def retrieve(self, group_by_doc) -> list[Detail]
    # Raises ValueError if any doc_name != "menu.md"

class CompositeRetriever(RetrieverInterface):
    def __init__(self, primary: RetrieverInterface, fallback: RetrieverInterface)
    async def retrieve(self, group_by_doc) -> list[Detail]
    # Delegates "menu.md" to primary, everything else to fallback
```

## Ontology Model (Turtle)

```turtle
@prefix : <http://saborcasero.com/menu#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .

:MenuItem a owl:Class .
:MenuSection a owl:Class .
:ItemOption a owl:Class .

:hasSection a owl:ObjectProperty .
:hasItem a owl:ObjectProperty .
:hasOption a owl:ObjectProperty .
:hasPrice a owl:DatatypeProperty .
:hasSize a owl:DatatypeProperty .

:Sopa a :MenuSection ; :sectionName "Sopa" ; :hasItem :CremaDeVerdura .
:CremaDeVerdura a :MenuItem ; :itemName "Crema de verdura" ; :hasPrice "—" .
# ... all items, options, prices modelled as instances
```

## Testing Strategy

| Layer | What | Approach |
|-------|------|----------|
| Unit | `OwlClient` query methods | Load `menu.ttl` in test fixture; assert deterministic results (same query 3x = same output) |
| Unit | `OwlRetriever` routing | Mock `OwlClient`; verify segment→SPARQL mapping for each pattern |
| Unit | `CompositeRetriever` delegation | Verify routing: menu.md goes to primary, other docs to fallback |
| Integration | Factory wiring | `get_retriever("owl")` returns CompositeRetriever wrapping both OwlRetriever and HybridRetriever |
| E2E | Pipeline with `retriever_type="owl"` | Run assistant; verify menu answers + non-menu answers still work |
| Validation | Ingest script | `ingest_menu_to_owl.py` output loaded by rdflib parses without error |

## Migration / Rollout

No migration required. Old `menu.md` chunks remain in ChromaDB but are never queried (CompositeRetriever routes menu.md to OWL). Rollback: set `retriever_type= "vector_db"` — ChromaDB path is untouched, OWL files become dead code.

## Open Questions

- [ ] Confirm `retriever_type: str` default: keep `"vector_db"` so existing users are unaffected; `"owl"` is opt-in
- [ ] Should `CompositeRetriever` be lazy (create HybridRetriever only when non-menu docs arrive)? Currently HybridRetriever does eager ingestion in factory — simplest to keep existing behavior
