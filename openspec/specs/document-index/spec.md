# Document Index Specification

## Purpose

Auto-index documents in `data/documents/` with structure extraction, change detection, and caching. Feeds `get_all_summaries()` with fresh content while preserving the consumer contract.

## Requirements

### Requirement: Content Analysis

Content Analyzer MUST extract sections from markdown via regex on `##` and `###` headers. If none found, treat entire document as a single section. MUST compute SHA256 hash of full content.

#### Scenario: Headers extracted

- GIVEN a markdown document with `##` headers
- WHEN processed
- THEN each header + body text is extracted as a named section with SHA256 hash

#### Scenario: No headers found

- GIVEN a `.txt` document with no markdown headers
- WHEN processed
- THEN entire content is a single unnamed section

#### Scenario: Empty document

- GIVEN a zero-byte document
- WHEN processed
- THEN sections are empty and no LLM enrichment call is made

### Requirement: Change Detection

On startup, DocumentCache MUST compare each document's SHA256 against cached hash. On mismatch, re-parse. If no cache exists, process all as new.

#### Scenario: Cached hash matches

- GIVEN cached entry with hash `abc123`
- WHEN document content is unchanged
- THEN cached sections/metadata are reused

#### Scenario: Hash mismatch

- GIVEN cached entry with hash `abc123`
- WHEN document content changes (hash `def456`)
- THEN document is re-parsed and cache entry updated

### Requirement: Cache Persistence

Cache SHALL be stored in `data/cache/document_cache.json` as a single file. Writes MUST use atomic pattern: write `.tmp`, fsync, rename. On corrupt JSON, rebuild from scratch and log warning.

#### Scenario: Corrupt cache file

- GIVEN `document_cache.json` with invalid JSON
- WHEN loading on startup
- THEN warning logged and cache rebuilt

#### Scenario: Partial write avoided

- GIVEN an atomic write in progress
- WHEN a crash occurs
- THEN original file is preserved (write targeted `.tmp`)

### Requirement: LLM Enrichment

On changed document, the system SHALL call one LLM call per document to generate a narrative summary. LLM summary MUST NOT replace section extraction (regex runs first). Enriched output SHALL contain both sections and summary.

#### Scenario: Changed document enriched

- GIVEN a document with hash mismatch
- WHEN LLM enrichment is enabled
- THEN one LLM call produces a summary, cached alongside extracted sections

### Requirement: Topic Mapping

Topic-to-document mapping MUST be configurable via `data/config/topic_document_map.yaml`. Not hardcoded. YAML maps `QueryTopic` values to filenames.

#### Scenario: YAML maps topic to document

- GIVEN YAML mapping `MENU → menu.md`
- WHEN `get_doc_for_topic(MENU)` called
- THEN returns `menu.md`

#### Scenario: YAML entry missing from filesystem

- GIVEN YAML entry for `obsolete.md`
- WHEN `obsolete.md` is absent from `data/documents/`
- THEN warning logged, document skipped

### Requirement: Document Auto-Discovery

Documents MUST be auto-discovered via filesystem scan of `data/documents/`. Adding/removing files reflects without code changes. All discovered documents appear in index; YAML config defines topic mapping.

#### Scenario: New file appears

- GIVEN a new `specials.md` in `data/documents/`
- WHEN index rebuilds
- THEN it appears in `get_all_summaries()` with generic topic mapping if absent from YAML

### Requirement: Backward Compatibility

`get_all_summaries()` MUST return same structural format: `- Document: {name}\n  Topics: [{topics}]\n  Content: {summary}`. Only content values become richer (sections + narrative summary). Template variable `{docs_summaries}` in classifier prompt SHALL remain unchanged.

#### Scenario: Classifier receives same template

- GIVEN classifier calls `get_all_summaries()`
- WHEN result is injected into prompt
- THEN `{docs_summaries}` has structurally identical format

### Requirement: Consumer Signature

`get_doc_for_topic(topic: QueryTopic) -> str` MUST keep same signature. `HybridClassifier.classify()` call site MUST NOT change.

#### Scenario: Classify call unchanged

- GIVEN a HybridClassifier instance
- WHEN `classify(message, summary_order, summary_conversation)` is called
- THEN it succeeds with no signature change
