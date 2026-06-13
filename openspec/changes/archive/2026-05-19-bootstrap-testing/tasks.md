## Tasks: bootstrap-testing

### Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~850 |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | PR 1 → PR 2 → PR 3 (stacked to main) |
| Delivery strategy | ask-on-risk |
| Chain strategy | stacked-to-main |

Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: stacked-to-main
400-line budget risk: High

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|------|------|-----------|-------|
| 1 | Config + helpers (infra) | PR 1 | base: main — pyproject.toml, conftest.py, mock repos, Settings.for_test() |
| 2 | Domain model tests | PR 2 | base: main — pure pydantic/enum tests, zero mocking |
| 3 | Application logic tests | PR 3 | base: main — test doubles from Phase 1, edge cases |

## Phase 1: Config + Test Helpers (~340 lines)

- [x] **1.1** Create `sabor_casero_assistant/pyproject.toml` with `[tool.pytest.ini_options]` (asyncio_mode=auto, testpaths=tests, pythonpath=["src"]), `[tool.coverage.run]` (source=src, branch=True), `[tool.coverage.report]` (exclude_lines), `[tool.black]` (line-length=100), `[tool.isort]` (profile=black), `[tool.mypy]` (ignore_missing_imports=True)
- [x] **1.2** Add `pytest-asyncio>=0.23.0`, `pytest-cov>=4.1.0` to `requirements.txt`
- [x] **1.3** Add `Settings.for_test()` classmethod to `src/config/environment.py` — returns instance with `_env_file=None` + overrides
- [x] **1.4** Create `tests/conftest.py` — sys.path setup, pytest_configure, shared fixtures (mock_llm_client, sample_order, sample_classification, temp_dirs, settings_override via monkeypatch)
- [x] **1.5** Create `tests/helpers/__init__.py`
- [x] **1.6** Create `tests/helpers/fixtures.py` — sample Order factory, sample OrderItem factory, sample Detail factory, sample UserQueryClassifier
- [x] **1.7** Create `tests/helpers/mock_llm_client.py` — MockLLMClient(AsyncMock) with canned `chat_completion` / `extract_json` return values
- [x] **1.8** Create `tests/helpers/mock_repositories.py` — InMemoryOrderRepository(OrderRepository), InMemorySessionRepository(SessionRepository) with dict-based storage
- [x] **Verify**: `pytest --co -v` discovers all test modules with 0 errors; `mypy tests/` passes

## Phase 2: Domain Tests (~220 lines)

- [ ] **2.1** Create `tests/domain/__init__.py`
- [ ] **2.2** Create `tests/domain/test_order_models.py` — OrderStatus enum values, OrderItem creation/validation (quantity ge=1, subtotal computed, to_summary format), Order CRUD (add_item, remove_item, update_item), Order computed fields (subtotal, total_amount, service_type, address, delivery_fee), ServiceDetails factory methods (create_delivery, create_pickup), DeliveryDetails.calculate_total_with_fee, PickupDetails.calculate_total_with_fee, Order.validate_order/is_valid, Order.to_summary/ to_dict
- [ ] **2.3** Create `tests/domain/test_classifier_intent.py` — QueryTopic enum values, QueryType enum values, DocumentSource enum values, Detail model validation (focus length validator), UserQueryClassifier default construction, get_conversation_strategy returns expected dict
- **Verify**: `pytest tests/domain/ -v` passes without .env file or API keys

## Phase 3: App Logic Tests (~290 lines)

- [ ] **3.1** Create `tests/application/__init__.py`
- [ ] **3.2** Create `tests/application/test_order_checklist.py` — OrderChecklist.get_next_field on empty/missing fields/complete orders, _field_is_missing per field type, _has_valid_items, _item_has_size_variants, get_checklist_summary produces correct [OK]/[WAITING] markers, get_retrieval_query returns expected strings
- [ ] **3.3** Create `tests/application/test_response_mixer.py` — ResponseMixer.combine with all 4 branches (order-only, info-only, both with mix rules, none), _apply_mix_rules for ordering+consulting vs consulting+ordering, determine_order returns correct strategy
- [ ] **3.4** Create `tests/application/test_utils.py` — build_prompt with valid/missing template, print_section output format, safe_json_string with markdown/missing/injection input, DateTimeEncoder handles datetime objects
- **Verify**: `pytest tests/application/ -v` passes with mock dependencies; `pytest --cov=src --cov-report=term -v` shows >90% on tested modules
