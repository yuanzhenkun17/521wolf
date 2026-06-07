# Test Layers

The suite keeps the existing flat `tests/` layout. Layering is applied with
pytest markers in `tests/conftest.py`, so existing commands such as `pytest` or
`pytest tests/test_util.py` still work.

## Markers

- `unit`: fast tests for helpers, pure functions, and narrow module behavior.
- `contract`: API, persistence, compatibility, and UI-backend response contracts.
- `integration`: cross-module graph, pipeline, storage, or batch behavior.
- `stress`: concurrency, atomicity, contention, CAS, retention, or similar cases.
- `smoke`: quick import-surface or minimal end-to-end health checks.

Markers may overlap. For example, a UI backend contract test with a thread-safe
assertion is marked as both `contract` and `stress`.

## Useful Commands

```powershell
uv run pytest
uv run pytest -m unit
uv run pytest -m contract
uv run pytest -m integration
uv run pytest -m stress
uv run pytest -m smoke
uv run pytest --collect-only -q
```

## Auto-Marking Rules

`tests/conftest.py` assigns markers by filename first:

- `test_ui_backend_app.py`, `test_storage_compat.py`, `test_storage_ids.py`,
  and `test_tools_cleanup_runs.py` are `contract`.
- `test_integration.py` is `integration` and `smoke`.
- `test_eval_pipeline.py`, `test_evolve_consolidate_apply.py`,
  `test_game_batch.py`, `test_storage_batch_transactions.py`, and
  `test_storage_runtime_replay.py` are `integration`.
- Everything else defaults to `unit`.

Test names containing terms such as `smoke`, `concurrent`, `thread_safe`,
`cas`, `atomic`, or `busy_timeout` receive the corresponding overlay marker.
