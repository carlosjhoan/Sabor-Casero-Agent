# Archive Report: owl-menu-retrieval

**Archived**: 2026-05-25
**Change**: owl-menu-retrieval
**Scope**: Deterministic OWL ontology + SPARQL replacement for ChromaDB vector search on `menu.md`
**SDD Cycle**: Complete

## Artifact Lineage

| Artifact | Engram ID | Filesystem Path |
|----------|-----------|-----------------|
| Proposal | #125 | `proposal.md` |
| Design | #156 | `design.md` |
| Tasks | #157 | `tasks.md` |
| Apply Progress | #158 | *(Engram only — no filesystem copy)* |
| Verify Report | #161 | `verify-report.md` |
| Archive Report | *(this)* | `archive-report.md` |

## Specs Synced

| Domain | Action | Details |
|--------|--------|---------|
| `menu-retrieval` | New capability | No delta specs existed — this was a new capability with no modified capabilities. |

## Archive Contents

| Artifact | Status |
|----------|--------|
| proposal.md | ✅ |
| design.md | ✅ |
| tasks.md | ✅ |
| apply-progress.md | ❌ (Engram only — no filesystem copy) |
| verify-report.md | ✅ |
| archive-report.md | ✅ |
| specs/ | ❌ (not produced — new capability, no modified specs) |

## Implementation Summary

### Phases Completed: 4 of 4 (13 of 13 tasks)

1. **Phase 1 — Foundation** (Tasks 1.1–1.3): `data/ontology/menu.ttl` (120 triples, 4 sections, 11 items, 12 PriceOptions, 6 ItemOptions), `src/infrastructure/owl_client.py` (307 lines, rdflib wrapper), `owl_ontology_path` config field.
2. **Phase 2 — Core Retrievers** (Tasks 2.1–2.3): `src/core/extractor/owl_retriever.py` (167 lines, keyword→SPARQL routing), `src/core/extractor/composite_retriever.py` (86 lines, routes by doc_name), `retriever_factory.py` wiring (`"owl"` → `CompositeRetriever`).
3. **Phase 3 — Ingestion Script** (Task 3.1): `scripts/ingest_menu_to_owl.py` (323 lines, one-shot parser/converter `menu.md` → `menu.ttl`).
4. **Phase 4 — Testing** (Tasks 4.1–4.5): 56 OWL-specific tests covering OwlClient (17), OwlRetriever (13), CompositeRetriever (6), RetrieverFactory (4), ingest script (16).

### Results

- **299 total tests** passing (including 56 OWL-specific), zero failures, zero skipped
- **Verification verdict**: PASS — no critical or warning issues
- All 6 in-scope deliverables confirmed present and correct
- All 5 design decisions followed (Composite over Monolithic, Static Ontology File, Keyword-based Query Routing, interface contracts, error resilience)

### Files Created (11)

```
data/ontology/menu.ttl                              # OWL ontology (120 triples)
src/infrastructure/owl_client.py                    # rdflib SPARQL wrapper
src/core/extractor/owl_retriever.py                 # Keyword→SPARQL router
src/core/extractor/composite_retriever.py           # Doc_name-based router
scripts/ingest_menu_to_owl.py                       # One-shot parser/converter
tests/infrastructure/test_owl_client.py             # 17 tests
tests/infrastructure/test_owl_retriever.py          # 13 tests
tests/infrastructure/test_composite_retriever.py    # 6 tests
tests/infrastructure/test_retriever_factory.py      # 4 tests
tests/infrastructure/test_ingest_menu_to_owl.py     # 16 tests
openspec/changes/archive/2026-05-25-owl-menu-retrieval/  # SDD artifacts
```

### Files Modified (2)

```
src/config/environment.py       # +owl_ontology_path field
src/core/extractor/retriever_factory.py  # +'owl' case
```

### Deviations from Design

1. **Routing order fix**: Design's keyword table had no priority. Implementation checks section keywords **before** full-menu keywords to prevent `"¿Qué hay de sopa?"` from matching `"qué hay"` (full menu) before `"sopa"` (section).
2. **`OwlClient` method naming**: Design specified `get_menu_summary()`; implementation uses `get_full_menu()` — functionally equivalent, naming was a trivial implementation decision.

### Issues Found & Fixed During Apply

1. **Parser `- ` item detection**: menu.md uses `- Crema de verdura` for Sopa items (no `### ITEM:` format). Fixed by adding `- ` prefix detection.
2. **Non-section `##` blocks**: Headers like `## NOTES` caused invalid Turtle generation. Fixed by adding skip_remaining logic.
3. **Accent normalization**: `_to_uri("Proteínas")` was producing `Protenas` (lost tilde after stripping). Fixed via `unicodedata.normalize('NFKD', ...)`.
4. **URI-safe names**: `_to_uri()` needed proper Unicode handling for Spanish accents to match hand-written `menu.ttl`.
5. **`owl_ontology_path` field**: Task 1.3 said to add `retriever_type` field, but that already existed. Added the correct `owl_ontology_path` field instead.

## Tech Debt Uncovered

| # | Issue | Severity | Recommendation |
|---|-------|----------|----------------|
| 1 | SPARQL f-string interpolation in `get_section_items()`, `get_item_price()`, `get_item_options()` | Low | Currently safe (hardcoded parameters), but should use parameterized SPARQL if user-provided strings are ever passed. |
| 2 | Ingest script path resolution assumes `scripts/` | Low | Add `--menu-md-path` and `--output-path` CLI args for flexibility. |
| 3 | No full-pipeline E2E test with `retriever_type="owl"` | Low | Existing tests cover each component in isolation; an E2E test would verify the full classifier→retriever→response path. |

## Key Learnings

- `unicodedata.normalize('NFKD', ...)` is essential for generating URI-safe names from Spanish text with accents — simple regex stripping loses tilde/n-tilde distinctions.
- Section keyword priority matters in keyword→SPARQL routing: check specific section keywords before broad full-menu keywords to avoid false matches.
- The CompositeRetriever pattern allowed zero changes to existing `HybridRetriever` code — a clean separation that kept the change additive and safe to roll back.
- OWL/SPARQL on a ~120-triple ontology is effectively instant (<1ms query time), making it a practical deterministic replacement for vector similarity on structured menu data.

## Rollback Plan

```bash
# Option A: Configuration rollback
# Set retriever_type="vector_db" in environment config

# Option B: Git revert
git revert <merge-commit>
```

No data loss, no migration. OWL files become dead code with no callers. ChromaDB path remains untouched with old `menu.md` chunks intact.

## SDD Cycle Complete

The owl-menu-retrieval change has been fully planned, designed, implemented, verified, and archived. Change folder moved to `archive/2026-05-25-owl-menu-retrieval/`. Ready for the next change.
