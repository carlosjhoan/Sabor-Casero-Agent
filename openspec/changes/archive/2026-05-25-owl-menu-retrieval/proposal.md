# Proposal: OWL Menu Retrieval

## Intent

Replace ChromaDB vector similarity search for `menu.md` with a deterministic OWL ontology + SPARQL approach. Vector search returns different chunks for the same semantic query asked differently (`"¿Qué hay hoy?"` vs `"¿Qué tienen para hoy?"`). An OWL model guarantees deterministic results — same logical query → same answer, regardless of phrasing.

## Scope

### In Scope
- **OWL ontology** (`data/ontology/menu.ttl`): Turtle file modelling menu sections (Sopa, Principio, Acompañamientos, Proteínas), items, prices, size variants (Corriente/mini), and OPTION sub-variants
- **SPARQL client** (`src/infrastructure/owl_client.py`): Reusable rdflib wrapper for loading/querying the ontology
- **OWL retriever** (`src/core/extractor/owl_retriever.py`): Implements `RetrieverInterface`, queries the ontology for menu-related topics only
- **Factory wiring** (`src/core/extractor/retriever_factory.py`): New `'owl'` option in `get_retriever()`
- **Config** (`src/config/environment.py`): Add `RAG_PROVIDER_OWL` setting or similar toggle
- **Ingestion script** (`scripts/ingest_menu_to_owl.py`): One-shot converter from `menu.md` → `menu.ttl`

### Out of Scope
- Removing ChromaDB or `HybridRetriever` — kept for non-menu documents (service_info.txt, waiter_guide.txt, about_us.txt)
- Migrating other documents to OWL — evaluation deferred
- Adding a full SPARQL endpoint or web UI
- Replacing the existing LLM extractor fallback (`'llm'` retriever way)
- Reranking or relevance scoring (not needed — SPARQL results are deterministic)

## Capabilities

### New Capabilities
- `menu-retrieval`: Deterministic menu query resolution via SPARQL against the OWL ontology. Covers section listing, item lookup, price queries, size variant questions, and OPTION sub-variant questions.

### Modified Capabilities
- None (pure implementation change — behavior contract unchanged)

## Approach

1. **Model the ontology**: Create `data/ontology/menu.ttl` with classes (`MenuItem`, `MenuSection`, `PriceOption`), properties (`hasSection`, `hasItem`, `hasPrice`, `hasSize`, `hasOption`), and instances derived from `menu.md`
2. **Build SPARQL client**: `OwlClient` loads `menu.ttl` via rdflib, exposes `query_deterministic(sparql: str) -> List[Dict]` and convenience methods (`get_menu_summary()`, `get_section_items()`, `get_item_price()`, `get_item_options()`)
3. **Build OWL retriever**: `OwlRetriever(retriever_interface.py)` checks `detail.file_source == "menu.md"` → routes to SPARQL. Other docs fall through to a secondary retriever (ChromaDB or LLM)
4. **Composite retriever**: Factory returns a `CompositeRetriever` that delegates `menu.md` to OWL and everything else to ChromaDB. This avoids a single-file change to the assistant pipeline
5. **Ingest script**: `scripts/ingest_menu_to_owl.py` reads `menu.md`, parses sections/items/prices/options, writes `menu.ttl`. Run once; output committed to repo

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `data/ontology/menu.ttl` | **New** | Turtle ontology file (committed, not generated at runtime) |
| `src/infrastructure/owl_client.py` | **New** | rdflib SPARQL wrapper |
| `src/core/extractor/owl_retriever.py` | **New** | OWL retriever implementing `RetrieverInterface` |
| `src/core/extractor/retriever_factory.py` | **Modified** | Add `'owl'` and `'composite'` options |
| `src/config/environment.py` | **Modified** | Add `RAG_PROVIDER_OWL` setting (or `retriever_type: enum`) |
| `scripts/ingest_menu_to_owl.py` | **New** | One-shot converter from `menu.md` to `menu.ttl` |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Ontology misses edge cases in menu.md (OPTIONS with mixed PRICE/PRICES) | Low | Cover all 4 items with non-trivial structures in the ontology; test each SPARQL query against real data |
| rdflib SPARQL performance on small ontology | Low | Ontology is ~50 triples — query time is sub-millisecond |
| Composite retriever adds complexity to factory | Medium | Keep `OwlRetriever` single-responsibility; composite is a thin router |

## Rollback Plan

Set `RAG_PROVIDER_OWL = False` or revert `retriever_type` to `"vector_db"`. The ChromaDB/HybridRetriever path remains untouched. OWL files (`owl_client.py`, `owl_retriever.py`, `menu.ttl`) become dead code with no callers — safe to leave.

## Dependencies

- `rdflib>=7.0.0` — already in `requirements.txt`

## Success Criteria

- [ ] Same SPARQL query always returns identical results (deterministic — verified by running the same query 3x)
- [ ] All 12+ SPARQL queries (section list, item lookup by name, price query, size variants, OPTION sub-variants) return correct results matching `menu.md`
- [ ] Pipeline continues to work: `owl` retriever selected → assistant answers menu questions → non-menu docs still served by ChromaDB
- [ ] `scripts/ingest_menu_to_owl.py` produces a valid `menu.ttl` (verified by loading with rdflib)
