# Tasks: Dynamic Document Index

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~300 |
| 400-line budget risk | Low |
| Chained PRs recommended | No |
| Suggested split | Single PR |
| Delivery strategy | ask-on-risk |
| Chain strategy | pending |

Decision needed before apply: Yes
Chained PRs recommended: No
Chain strategy: pending
400-line budget risk: Low

## Phase 1: Foundation — ContentAnalyzer + DocumentCache

- [x] 1.1 Create `src/core/knowledge/content_analyzer.py` with `Section`/`AnalysisResult` dataclasses and `ContentAnalyzer` class — regex HEADER_RE (`##`/`###`) + UPPERCASE_RE, SHA256 computation, full plaintext fallback for no-headers docs
- [x] 1.2 Create `src/core/knowledge/document_cache.py` with `DocEntry` dataclass and `DocumentCache` class — atomic writes via `.tmp` + `os.replace()`, `rebuild_if_corrupt()` on `JSONDecodeError`, `get()`/`put()`/`has_changed()` methods
- [x] 1.3 Create `data/config/topic_document_map.yaml` with `topic_to_doc:` mapping (menu→`menu.md`, hours/delivery/payment/complaint/general→`service_info.txt`, cutlery/adicional/disrespectful→`waiter_guide.txt`, about→`about_us.txt`)
- [x] 1.4 Create `data/cache/` directory, create root `.gitignore` with `data/cache/` entry

## Phase 2: Registry Refactor — Dynamic Discovery + YAML Loading

- [x] 2.1 Refactor `DocumentRegistry.__init__` — accept `docs_dir`, `cache_path`, `config_path` params; scan `data/documents/` via `Path.iterdir()`; load YAML via `yaml.safe_load`; instantiate `DocumentCache`; per-file hash check → re-parse or reuse
- [x] 2.2 Replace hardcoded `_docs` list — `get_all_summaries()` derives from cache sections + topic mapping; `get_doc_for_topic()` reads YAML + checks file exists; `list_all_documents()` returns scanned files
- [x] 2.3 Handle edge cases: YAML entry with missing file logs warning + skips; unmapped doc appears with generic `[UNMAPPED]` topic; corrupt cache triggers rebuild + warning

## Phase 3: LLM Enrichment

- [x] 3.1 Wire LLM enrichment call in `DocumentRegistry.__init__` — for each changed document (hash mismatch), fire one LLM call via `llm_client.generate()`, store `summary` in cache alongside sections; skip LLM for unchanged docs and empty docs

## Phase 4: Tests

- [x] 4.1 Write `tests/domain/test_content_analyzer.py` — test all 4 real documents, empty file returns empty sections, plaintext `.txt` returns single unnamed section, SHA256 stability across repeated calls
- [x] 4.2 Write `tests/domain/test_document_cache.py` — corrupt JSON triggers rebuild, hash match reuses cached entry, hash mismatch triggers re-parse, atomic write survives simulated crash (verify `.tmp` not left behind)
- [x] 4.3 Update `tests/domain/test_document_registry.py` — remove `len(registry._docs) == 4` assertions; test init with `tmp_path` fixture + real copied documents + YAML; verify `get_doc_for_topic()` returns correct filenames; verify `get_all_summaries()` format
- [x] 4.4 Write `tests/domain/test_document_index_integration.py` — full startup with `tmp_path` docs dir + YAML + cache + mock LLM; verify: new file appears in summaries, deleted file excluded, LLM fires only for changed docs
