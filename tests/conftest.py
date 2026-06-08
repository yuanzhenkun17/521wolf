"""Shared pytest configuration.

The test suite is layered with markers instead of directory moves, so legacy
commands such as ``pytest`` and ``pytest tests/test_util.py`` remain unchanged.
"""
import sys
from pathlib import Path

import pytest

_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


_PRIMARY_LAYER_MARKERS = {"unit", "contract", "integration"}

_FILE_MARKERS: dict[str, tuple[str, ...]] = {
    "test_api_contracts.py": ("contract",),
    "test_ui_backend_app.py": ("contract",),
    "test_storage_compat.py": ("contract",),
    "test_storage_ids.py": ("contract",),
    "test_tools_cleanup_runs.py": ("contract",),
    "test_integration.py": ("integration", "smoke"),
    "test_eval_pipeline.py": ("integration",),
    "test_evolve_consolidate_apply.py": ("integration",),
    "test_game_batch.py": ("integration",),
    "test_storage_batch_transactions.py": ("integration",),
    "test_storage_runtime_replay.py": ("integration",),
}

_STRESS_NAME_TOKENS = (
    "atomic",
    "busy_timeout",
    "cas",
    "concurrent",
    "contention",
    "parallel",
    "race",
    "retention",
    "stress",
    "thread_safe",
)


def pytest_configure(config: pytest.Config) -> None:
    for marker in (
        "unit: fast tests for helpers, pure functions, and narrow module behavior",
        "contract: API, persistence, compatibility, and UI-backend response contracts",
        "integration: cross-module graph, pipeline, storage, or batch behavior",
        "smoke: quick import-surface or minimal end-to-end health checks",
        "stress: concurrency, atomicity, contention, CAS, retention, or similar cases",
        "postgres: tests that require an isolated PostgreSQL database",
    ):
        config.addinivalue_line("markers", marker)


@pytest.fixture(autouse=True)
def _disable_real_langfuse_in_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep local .env Langfuse credentials from making pytest hit the network."""
    monkeypatch.setenv("LANGFUSE_TRACING_ENABLED", "false")


def _item_filename(item: pytest.Item) -> str:
    try:
        return Path(str(item.path)).name
    except AttributeError:
        return Path(str(item.fspath)).name


def _inferred_layer_markers(item: pytest.Item) -> set[str]:
    markers = set(_FILE_MARKERS.get(_item_filename(item), ()))
    node_name = item.nodeid.lower()

    if "smoke" in node_name:
        markers.add("smoke")

    if any(token in node_name for token in _STRESS_NAME_TOKENS):
        markers.add("stress")

    if not markers.intersection(_PRIMARY_LAYER_MARKERS):
        markers.add("unit")

    return markers


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Infer layer markers from stable file/name conventions."""
    for item in items:
        existing = {mark.name for mark in item.iter_markers()}
        for marker in sorted(_inferred_layer_markers(item) - existing):
            item.add_marker(getattr(pytest.mark, marker))
