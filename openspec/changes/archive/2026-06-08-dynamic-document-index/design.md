# Design: Dynamic Document Index

## Technical Approach

Replace hardcoded `DocumentReference` list in `DocumentRegistry` with a pipeline that auto-discovers `data/documents/`, extracts section structure via regex + SHA256, caches results atomically, and maps topics via external YAML. LLM enrichment fires once per changed document (gated by flag). All four consumer signatures (`get_doc_for_topic`, `get_all_summaries`, `list_all_documents`) remain identical.

## Architecture Decisions

### Decision: ContentAnalyzer as stateless class

| Option | Tradeoff | Decision |
|--------|----------|----------|
| Module-level functions | Simpler, no instantiation needed | ❌ — project uses classes everywhere for analyzers |
| Stateless class with public method | Consistent with project patterns, easy to mock in tests | ✅ |

One public method: `analyze(filepath: Path) -> AnalysisResult`. Pure computation (regex + SHA256) — no IO beyond file read.

### Decision: Atomic cache writes via tmp + rename

| Option | Tradeoff | Decision |
|--------|----------|----------|
| `json.dump` directly to cache path | Partial write on crash corrupts cache | ❌ |
| Write `.tmp` → `os.replace()` → sync dir | Atomic at filesystem level, zero corruption risk | ✅ (stdlib only) |

`DocumentCache.rebuild_if_corrupt()` catches `json.JSONDecodeError` on load, logs warning, starts fresh.

### Decision: LLM enrichment lives in DocumentRegistry

| Option | Tradeoff | Decision |
|--------|----------|----------|
| In ContentAnalyzer | Couples structural analysis with LLM call | ❌ |
| In DocumentCache | Cache shouldn't have side effects | ❌ |
| **In DocumentRegistry `__init__`** | Orchestrates analyzer + cache + LLM at right level; always active for changed docs | ✅ |

Fire once per changed doc, cache enriched result. No LLM call for unchanged docs.

### Decision: YAML for topic→document mapping

| Option | Tradeoff | Decision |
|--------|----------|----------|
| Keep mapping hardcoded in Python | Requires code change to remap topics | ❌ |
| External `data/config/topic_document_map.yaml` | Ops-friendly, validated at startup, matches current behavior exactly | ✅ |

## Data Flow

```
DocumentRegistry.__init__()
  │
  ├── 1. Scan data/documents/ → 4 files found
  ├── 2. Load topic_document_map.yaml → {topic: filename} dict
  ├── 3. Load document_cache.json → {filename: DocEntry}
  │
  └── 4. For each file in data/documents/:
         │
         ├── SHA256(file) == cached SHA256?
         │     ├── YES → reuse cached DocEntry
         │     └── NO  → ContentAnalyzer.analyze(file)
         │                   │
         │                   ├── regex → sections[{"heading", "body"}]
                 │                   ├── hash → sha256 hexdigest
                 │                   └── LLM call → narrative summary
                 │                       cache.put(file, DocEntry{...})
         │
         └── get_all_summaries() formats from cache:
               "- Document: menu.md\n  Sections: [MENU_EXTRACTION, METADATA, ...]\n  Summary: ..."
```

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `src/core/knowledge/content_analyzer.py` | **Create** | Stateless class: regex sections + SHA256 |
| `src/core/knowledge/document_cache.py` | **Create** | JSON cache with atomic writes |
| `src/core/knowledge/registry.py` | **Modify** | Remove hardcoded `_docs`; use dynamic derivation |
| `data/config/topic_document_map.yaml` | **Create** | External topic→filename mapping |
| `data/cache/document_cache.json` | **Create** | Auto-generated cache (gitignored) |
| `src/core/classifier/hybrid.py` | No change | `DocumentRegistry()` still works — no signature change |
| `src/core/response/order_response_builder.py` | No change | `DocumentRegistry()` still works |
| `src/core/extractor/vector_extractor.py` | No change | `DocumentRegistry()` still works |
| `src/core/assistant.py` | No change | `doc_registry.get_all_summaries()` still works |
| `tests/domain/test_document_registry.py` | **Modify** | Update to test dynamic behavior |

## Interfaces / Contracts

```python
# content_analyzer.py
@dataclass
class Section:
    heading: str          # "SECTION: Sopa" or "" for no-heading docs
    body: str             # text under heading

@dataclass
class AnalysisResult:
    sections: list[Section]
    sha256: str
    raw_text: str

class ContentAnalyzer:
    HEADER_RE = re.compile(r'^#{2,3}\s+(.+)$', re.MULTILINE)
    UPPERCASE_RE = re.compile(r'^([A-Z][A-Z\s]+):$', re.MULTILINE)

    @staticmethod
    def analyze(filepath: Path) -> AnalysisResult: ...

# document_cache.py
@dataclass
class DocEntry:
    filename: str
    sha256: str
    sections: list[Section]
    summary: str = ""
    last_updated: str = ""  # ISO timestamp

class DocumentCache:
    path: Path
    _data: dict[str, DocEntry]

    def get(self, filename: str) -> DocEntry | None: ...
    def put(self, filename: str, entry: DocEntry) -> None: ...  # atomic write
    def has_changed(self, filename: str, sha256: str) -> bool: ...
    def rebuild_if_corrupt(self) -> None: ...

# registry.py (refactored)
class DocumentRegistry:
    def __init__(self, docs_dir: str = "data/documents",
                 cache_path: str = "data/cache/document_cache.json",
                 config_path: str = "data/config/topic_document_map.yaml"):
        # 1. Scan docs_dir
        # 2. Load YAML config
        # 3. Load cache
        # 4. For each file: check hash → analyze/LLM as needed
        # 5. Build topic→file index from YAML
    def get_doc_for_topic(self, topic: QueryTopic) -> str: ...  # exact same signature
    def get_all_summaries(self) -> str: ...  # exact same format
    def list_all_documents(self) -> list[str]: ...
```

### YAML Schema (topic_document_map.yaml)

```yaml
# Maps QueryTopic enum values → document filenames
topic_to_doc:
  menu: menu.md
  ingredients: menu.md
  special_offers: menu.md
  hours: service_info.txt
  delivery: service_info.txt
  payment: service_info.txt
  complaint: service_info.txt
  general: service_info.txt
  cutley_request: waiter_guide.txt
  adicional_juice: waiter_guide.txt
  disrespectful_customer: waiter_guide.txt
  about: about_us.txt
```



## Testing Strategy

| Layer | What | How |
|-------|------|-----|
| Unit | ContentAnalyzer regex extraction | `test_content_analyzer.py` — 4 real docs + empty + plaintext + no-headers cases |
| Unit | DocumentCache atomic write | `test_document_cache.py` — corrupt JSON rebuild, hash match/mismatch, .tmp crash safety |
| Unit | DocumentRegistry new init | `test_document_registry.py` — YAML loading, auto-discovery, YAML entry missing from disk, fallback for unmapped docs |
| Integration | Registry + Cache + Analyzer | `test_document_index_integration.py` — full startup flow with temp directories, LLM enrichment always active |
| Existing | Updates to `test_document_registry.py` | Remove hardcoded-length assertions; test dynamic discovery with temp `data/documents/` |

## Migration / Rollback

No migration required. The new `get_all_summaries()` returns the same structural format as before — only content derives from real files instead of hardcoded strings. Rollback: revert `registry.py`, delete new files, remove `data/config/` and `data/cache/`.

## Open Questions

None.
