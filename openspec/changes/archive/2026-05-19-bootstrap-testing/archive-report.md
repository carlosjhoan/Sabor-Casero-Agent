# Archive Report: bootstrap-testing

**Archived**: 2026-05-19
**Change**: bootstrap-testing
**Scope**: Testing infrastructure + 123 unit tests
**SDD Cycle**: Complete

## Artifact Lineage

| Artifact | Engram ID | Filesystem Path |
|----------|-----------|-----------------|
| Proposal | #44 | *(Engram only)* |
| Tasks | #46 | `tasks.md` |
| Apply Progress (Phase 3) | #48 | `apply-progress.md` |
| Archive Report | *(this)* | `archive-report.md` |

> **Note**: No `spec` or `design` artifacts were produced for this change. The proposal directly fed into tasks without intermediate spec or design phases, as this was a pure infrastructure/testing change with no user-facing behavior changes.

## Specs Synced

| Domain | Action | Details |
|--------|--------|---------|
| *(none)* | No-op | No delta specs existed — this was an infrastructure-only change (testing infra + test files). No main specs were affected. |

## Archive Contents

| Artifact | Status |
|----------|--------|
| proposal.md | ❌ (Engram only — no filesystem copy) |
| tasks.md | ✅ |
| apply-progress.md | ✅ |
| archive-report.md | ✅ |
| specs/ | ❌ (not produced — infrastructure-only change) |
| design.md | ❌ (not produced — no design phase needed) |
| verify-report.md | ❌ (not produced — verification was inline in apply-progress) |

## Implementation Summary

### Phases Completed: 3 of 3

1. **Phase 1 — Config + Test Helpers**: `pyproject.toml`, `Settings.for_test()`, `conftest.py`, helper fixtures, `MockLLMClient`, in-memory repository stubs
2. **Phase 2 — Domain Tests**: 56 tests across 4 modules — order models (32), classifier intent (10), input guard (8), document registry (6)
3. **Phase 3 — Application Tests**: 67 tests across 4 modules — order checklist (28), response mixer (11), info response builder (9), utils (9), plus additional edge case coverage

### Results

- **123 tests**, all passing
- Zero LLM calls, zero I/O (except `tmp_path` in `test_utils`)
- All tests synchronous, no `.env` or API keys needed

### Files Created (18)

```
pyproject.toml                              # pytest, coverage, black, isort, mypy config
tests/conftest.py                           # Shared fixtures
tests/__init__.py
tests/domain/__init__.py
tests/domain/test_order_models.py           # 32 tests
tests/domain/test_classifier_intent.py      # 10 tests
tests/domain/test_input_guard.py            # 8 tests
tests/domain/test_document_registry.py      # 6 tests
tests/application/__init__.py
tests/application/test_order_checklist.py   # 36 tests
tests/application/test_response_mixer.py    # 11 tests
tests/application/test_info_response_builder.py  # 9 tests
tests/application/test_utils.py             # 9 tests
tests/helpers/__init__.py
tests/helpers/fixtures.py                   # Test data factories
tests/helpers/mock_llm_client.py            # MockLLMClient
tests/helpers/mock_repositories.py          # InMemory repositories
openspec/changes/archive/2026-05-19-bootstrap-testing/  # SDD artifacts
```

### Files Modified (2)

```
requirements.txt                # +pytest-asyncio, pytest-cov
src/config/environment.py       # +Settings.for_test()
```

## Tech Debt Uncovered

| # | Issue | Severity | Recommendation |
|---|-------|----------|----------------|
| 1 | `_field_is_missing("observations")` always returns `True` — bug in `order_response_builder.py` | Medium | Fix in a future SDD change |
| 2 | Legacy methods in `UserQueryClassifier` reference removed fields → `AttributeError` | Low | Remove dead code or add `try/except` |
| 3 | `json_oder_repository.py` filename typo (missing 'r') | Low | Rename in future cleanup pass |
| 4 | Pydantic-settings v2 incompatibility with nullable `str` fields (9 fields typed `str = Field(default=None)`) | Medium | Fix model types or add a Settings validator |

## Key Learnings

- `pydantic-settings` v2 rejects `_env_file=None` for models with nullable `str` fields — workaround detects these dynamically with placeholders
- Testing order models required understanding `OrderResponseBuilder`'s `_field_is_missing` logic, which has an existing bug around the `observations` field
- `make_sample_order()` fixtures need consistent item setup (principle must be set on ALL items)
- The change was additive-only (no existing behavior modified), making rollback trivial

## Rollback Plan

```bash
git revert <merge-commit>
```

No data loss, no migration. Tests, infra, and config are all additive — removing them restores the previous state without side effects.

## SDD Cycle Complete

The bootstrap-testing change has been fully planned, implemented, verified, and archived.
Ready for the next change.
