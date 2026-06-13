# Tasks: OWL Menu Retrieval

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~500 (485 new + 15 modified) |
| 400-line budget risk | Medium |
| Chained PRs recommended | Yes |
| Suggested split | PR 1: Foundation → PR 2: Retrievers → PR 3: Script + Tests |
| Delivery strategy | ask-on-risk |
| Chain strategy | pending |

Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: pending
400-line budget risk: Medium

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|------|------|-----------|-------|
| 1 | Ontology + client + config | PR 1 | menu.ttl, owl_client.py, environment.py — no pipeline dependency |
| 2 | Retriever layer + factory wiring | PR 2 | owl_retriever.py, composite_retriever.py, retriever_factory.py — depends on PR 1 |
| 3 | Ingest script + all tests | PR 3 | ingest_menu_to_owl.py + tests for all components — depends on PR 2 |

## Phase 1: Foundation / Infrastructure

- [x] 1.1 Create `data/ontology/menu.ttl` — Turtle OWL ontology with MenuSection, MenuItem, ItemOption classes; instances for all menu items from menu.md
- [x] 1.2 Create `src/infrastructure/owl_client.py` — OwlClient class wrapping rdflib: load menu.ttl, expose query_deterministic() + typed helpers
- [x] 1.3 Add `owl_ontology_path: str = "data/ontology/menu.ttl"` to `src/config/environment.py`

## Phase 2: Core Retrievers

- [x] 2.1 Create `src/core/extractor/owl_retriever.py` — implements RetrieverInterface, keyword→SPARQL routing from detail.segment, errors on non-menu docs
- [x] 2.2 Create `src/core/extractor/composite_retriever.py` — wraps OwlRetriever + HybridRetriever, routes by doc_name
- [x] 2.3 Add `"owl"` → CompositeRetriever(OwlRetriever, HybridRetriever) case to `retriever_factory.py`

## Phase 3: Ingestion Script

- [x] 3.1 Create `scripts/ingest_menu_to_owl.py` — one-shot parser: reads menu.md sections/items/prices/options, writes valid menu.ttl

## Phase 4: Testing

- [x] 4.1 Unit tests for OwlClient — load menu.ttl fixture, assert deterministic results (same query ×3 = same output)
- [x] 4.2 Unit tests for OwlRetriever — mock OwlClient, verify each keyword pattern maps to correct SPARQL template
- [x] 4.3 Unit tests for CompositeRetriever — verify menu.md routed to primary, other docs to fallback
- [x] 4.4 Integration test for factory — get_retriever("owl") returns CompositeRetriever with both inner retrievers
- [x] 4.5 Validation test for ingest script — script output loads without error in rdflib
