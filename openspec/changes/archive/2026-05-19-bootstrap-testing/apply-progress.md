# Apply Progress: bootstrap-testing — Phase 1

**Change**: bootstrap-testing
**Phase**: 1 (Config + Test Helpers)
**Status**: Complete

## Completed Tasks

- [x] 1.1 Create `pyproject.toml` — pytest, coverage, black, isort, mypy config
- [x] 1.2 Add `pytest-asyncio>=0.23.0`, `pytest-cov>=4.1.0` to `requirements.txt`
- [x] 1.3 Add `Settings.for_test()` to `src/config/environment.py`
- [x] 1.4 Create `tests/conftest.py` — shared fixtures and path setup
- [x] 1.5 Create `tests/helpers/__init__.py`
- [x] 1.6 Create `tests/helpers/fixtures.py` — Order/service/classification factories
- [x] 1.7 Create `tests/helpers/mock_llm_client.py` — MockLLMClient
- [x] 1.8 Create `tests/helpers/mock_repositories.py` — InMemoryOrderRepository, InMemorySessionRepository
- [x] **Verify**: `pytest --co -v` collects 0 tests; `Settings.for_test()` returns valid instance; `pyproject.toml` parses

## Files Changed

| File | Action | What Was Done |
|------|--------|---------------|
| `pyproject.toml` | Created | Tool configs for pytest, coverage, black, isort, mypy |
| `requirements.txt` | Modified | Added pytest-asyncio, pytest-cov |
| `src/config/environment.py` | Modified | Added `Settings.for_test()` classmethod |
| `tests/conftest.py` | Created | Shared fixtures, sys.path, mock_llm_client, test_settings, temp_data_dir |
| `tests/helpers/__init__.py` | Created | Empty package init |
| `tests/helpers/fixtures.py` | Created | Order/service classification factories matching real models |
| `tests/helpers/mock_llm_client.py` | Created | MockLLMClient (AsyncMock) for pipeline tests |
| `tests/helpers/mock_repositories.py` | Created | InMemoryOrderRepository, InMemorySessionRepository |
| `openspec/changes/bootstrap-testing/tasks.md` | Created | Task tracking with Phase 1 marked complete |
| `openspec/changes/bootstrap-testing/apply-progress.md` | Created | This file |

## Deviations from Task Spec

1. **`mock_repositories.py`** — Task spec had simplified method signatures (`save()`, `delete()`, etc.). Actual implementation matches the real interfaces (`save_order()`, `delete_order()`, `create_order()`, plus all `SessionRepository` abstract methods). Extra convenience methods (`get_all_orders()`, `clear()`) added for test assertions.

2. **`fixtures.py`** — Task spec used field names from an older model version (`name=` instead of `protein=`, `OrderType` instead of `ServiceCategory`, etc.). Actual implementation uses the real model field names from `src/core/order/domain/models.py` and `src/core/classifier/intent.py`.

3. **`Settings.for_test()`** — Task spec used `_env_file=None` approach, but pydantic-settings v2 rejects `None` for `str` fields when no .env is loaded. Implementation uses auto-detection of nullable str fields with safe placeholder defaults.

## Issues Found

- **`pydantic-settings` compatibility**: The `_env_file=None` pattern from the task spec doesn't work with pydantic-settings v2 when the model has `str = Field(default=None)` fields. Workaround: detect these fields dynamically and provide placeholder values. This is a pre-existing model issue (9 fields typed `str` with `default=None`), not caused by this change.

## Verification Results

| Check | Status |
|-------|--------|
| `pyproject.toml` parse | ✅ Parses with tomllib |
| `Settings.for_test()` | ✅ Returns valid instance |
| `pytest --co -v` | ✅ Collects 0 items (expected) |
| All helper imports | ✅ All modules import cleanly |
