from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path
from typing import Any

from app.config import PathConfig


SPEC = """
id: sync-contract-v1
version: 1
name: Sync Contract
description: Langfuse dataset sync contract
target_type: role_version
roles: [seer, witch]
game_count: 2
max_days: 5
paired_seed: true
seed_set_id: sync-contract-seeds
seed_start: 900000
"""


SEED_SET = """
id: sync-contract-seeds
purpose: sync_contract
version: 1
target_type: role_version
seeds: [910001, 910009, 910017]
enabled: true
"""


def _write_registry(root: Path) -> None:
    spec_dir = root / "data" / "benchmarks"
    seed_dir = root / "data" / "benchmark_seed_sets"
    spec_dir.mkdir(parents=True)
    seed_dir.mkdir(parents=True)
    (spec_dir / "sync-contract-v1.yaml").write_text(SPEC, encoding="utf-8")
    (seed_dir / "sync-contract-seeds.yaml").write_text(SEED_SET, encoding="utf-8")


def _load_tool(monkeypatch: Any):
    monkeypatch.delitem(sys.modules, "app.tools.sync_langfuse_datasets", raising=False)
    return importlib.import_module("app.tools.sync_langfuse_datasets")


class FakeClient:
    def __init__(self) -> None:
        self.datasets: list[dict[str, Any]] = []
        self.items: list[dict[str, Any]] = []

    def create_dataset(self, **kwargs: Any) -> None:
        self.datasets.append(kwargs)

    def create_dataset_item(self, **kwargs: Any) -> None:
        self.items.append(kwargs)


def test_dry_run_builds_datasets_without_observability(monkeypatch: Any, tmp_path: Path) -> None:
    _write_registry(tmp_path)
    fake_observability = types.ModuleType("app.services.observability")
    fake_observability.get_langfuse_client = lambda: (_ for _ in ()).throw(
        AssertionError("dry-run must not load Langfuse client")
    )
    monkeypatch.setitem(sys.modules, "app.services.observability", fake_observability)
    tool = _load_tool(monkeypatch)

    report = tool.sync_langfuse_datasets(paths=PathConfig(root=tmp_path))

    dataset = report["datasets"][0]
    item_ids = [item["item_id"] for item in dataset["items"]]
    assert report["dry_run"] is True
    assert dataset["name"] == "sync-contract-v1@v1"
    assert item_ids == [
        "sync-contract-v1@v1:sync-contract-seeds:910001",
        "sync-contract-v1@v1:sync-contract-seeds:910009",
    ]
    assert dataset["items"][0]["input"]["seed"] == 910001
    assert dataset["items"][0]["metadata"]["item_name"] == item_ids[0]


def test_apply_uses_observability_client_and_idempotent_item_ids(monkeypatch: Any, tmp_path: Path) -> None:
    _write_registry(tmp_path)
    client = FakeClient()
    fake_observability = types.ModuleType("app.services.observability")
    fake_observability.get_langfuse_client = lambda: client
    monkeypatch.setitem(sys.modules, "app.services.observability", fake_observability)
    tool = _load_tool(monkeypatch)

    report = tool.sync_langfuse_datasets(apply=True, paths=PathConfig(root=tmp_path))

    assert report["dry_run"] is False
    assert report["applied"][0]["name"] == "sync-contract-v1@v1"
    assert client.datasets[0]["name"] == "sync-contract-v1@v1"
    contract_items = [item for item in client.items if item["dataset_name"] == "sync-contract-v1@v1"]
    assert [item["dataset_name"] for item in contract_items] == ["sync-contract-v1@v1", "sync-contract-v1@v1"]
    assert [item["id"] for item in contract_items] == [
        "sync-contract-v1@v1:sync-contract-seeds:910001",
        "sync-contract-v1@v1:sync-contract-seeds:910009",
    ]
    assert contract_items[0]["input"]["evaluation_set_id"] == "sync-contract-v1@v1"
    assert contract_items[0]["expected_output"]["metrics"]["primary"] == "avg_role_score"


def test_apply_without_langfuse_config_reports_error(monkeypatch: Any, tmp_path: Path) -> None:
    _write_registry(tmp_path)
    fake_observability = types.ModuleType("app.services.observability")
    fake_observability.get_langfuse_client = lambda: None
    monkeypatch.setitem(sys.modules, "app.services.observability", fake_observability)
    tool = _load_tool(monkeypatch)

    report = tool.sync_langfuse_datasets(apply=True, paths=PathConfig(root=tmp_path))

    assert report["dry_run"] is False
    assert report["applied"] == []
    assert "Langfuse is not configured" in report["error"]


def test_main_apply_without_config_exits_non_crashing(monkeypatch: Any, tmp_path: Path, capsys: Any) -> None:
    _write_registry(tmp_path)
    fake_observability = types.ModuleType("app.services.observability")
    fake_observability.get_langfuse_client = lambda: None
    monkeypatch.setitem(sys.modules, "app.services.observability", fake_observability)
    tool = _load_tool(monkeypatch)
    original_build_sync_plan = tool.build_sync_plan
    monkeypatch.setattr(tool, "build_sync_plan", lambda paths=None: original_build_sync_plan(PathConfig(root=tmp_path)))

    exit_code = tool.main(["--apply"])
    output = capsys.readouterr().out

    assert exit_code == 2
    assert "Langfuse is not configured" in output
