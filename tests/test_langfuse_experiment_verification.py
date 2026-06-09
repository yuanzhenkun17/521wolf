from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any

from app.config import PathConfig


SPEC = """
id: verify-contract-v1
version: 1
name: Verify Contract
description: Langfuse experiment verification contract
target_type: role_version
roles: [seer, witch]
game_count: 2
max_days: 5
paired_seed: true
seed_set_id: verify-contract-seeds
seed_start: 900000
"""


SEED_SET = """
id: verify-contract-seeds
purpose: verify_contract
version: 1
target_type: role_version
seeds: [920001, 920009, 920017]
enabled: true
"""


def _write_registry(root: Path) -> None:
    spec_dir = root / "data" / "benchmarks"
    seed_dir = root / "data" / "benchmark_seed_sets"
    spec_dir.mkdir(parents=True)
    seed_dir.mkdir(parents=True)
    (spec_dir / "verify-contract-v1.yaml").write_text(SPEC, encoding="utf-8")
    (seed_dir / "verify-contract-seeds.yaml").write_text(SEED_SET, encoding="utf-8")


def _load_tool(monkeypatch: Any):
    monkeypatch.delitem(sys.modules, "app.tools.verify_langfuse_experiments", raising=False)
    return importlib.import_module("app.tools.verify_langfuse_experiments")


def _valid_game_payload() -> dict[str, Any]:
    return {
        "batch_id": "verify_batch",
        "games": [
            {
                "game_id": "verify_batch_game_001",
                "seed": 920001,
                "evaluation_set_id": "verify-contract-v1@v1",
                "seed_set_id": "verify-contract-seeds",
                "langfuse_trace_id": "trace-001",
                "langfuse_trace_url": "https://langfuse.local/project/proj/traces/trace-001",
                "langfuse_dataset_name": "verify-contract-v1@v1",
                "langfuse_dataset_item_id": "verify-contract-v1@v1:verify-contract-seeds:920001",
                "langfuse_experiment_name": "verify-contract-v1",
                "langfuse_run_name": "verify_batch:seer",
                "langfuse_dataset_run_id": "dataset-run-001",
                "langfuse_dataset_run_item_id": "dataset-run-item-001",
                "langfuse_experiment_url": (
                    "https://langfuse.local/project/proj/datasets/dataset-001/runs/dataset-run-001"
                ),
            }
        ],
    }


def _env_configured() -> dict[str, str]:
    return {
        "LANGFUSE_TRACING_ENABLED": "true",
        "LANGFUSE_PUBLIC_KEY": "pk-test-secret-value",
        "LANGFUSE_SECRET_KEY": "sk-test-secret-value",
        "LANGFUSE_BASE_URL": "https://langfuse.local/api?private=token",
        "LANGFUSE_ENVIRONMENT": "test",
        "LANGFUSE_RELEASE": "phase-5b",
    }


class _RemoteDataset:
    def __init__(self, item_ids: list[str]) -> None:
        self.items = [{"id": item_id, "metadata": {"item_name": item_id}} for item_id in item_ids]


class _FakeRemoteClient:
    def __init__(self, item_ids_by_dataset: dict[str, list[str]]) -> None:
        self.item_ids_by_dataset = item_ids_by_dataset
        self.calls: list[dict[str, Any]] = []

    def get_dataset(self, name: str, **kwargs: Any) -> _RemoteDataset | None:
        self.calls.append({"name": name, "kwargs": kwargs})
        item_ids = self.item_ids_by_dataset.get(name)
        if item_ids is None:
            return None
        return _RemoteDataset(item_ids)


def test_dry_run_verifier_uses_local_plan_payloads_and_redacts_config(monkeypatch: Any, tmp_path: Path) -> None:
    _write_registry(tmp_path)
    tool = _load_tool(monkeypatch)

    report = tool.verify_langfuse_experiments(
        paths=PathConfig(root=tmp_path),
        env=_env_configured(),
        payloads=[_valid_game_payload()],
    )

    assert report["dry_run"] is True
    assert report["status"] == "pass"
    assert report["langfuse_config"]["configured"] is True
    assert report["langfuse_config"]["public_key_configured"] is True
    assert report["langfuse_config"]["secret_key_configured"] is True
    assert "pk-test-secret-value" not in str(report)
    assert "sk-test-secret-value" not in str(report)
    assert "private=token" not in str(report)
    assert report["dataset_sync_plan"]["dataset_count"] >= 1

    verify_dataset = next(
        dataset
        for dataset in report["dataset_sync_plan"]["datasets"]
        if dataset["name"] == "verify-contract-v1@v1"
    )
    assert verify_dataset["item_count"] == 2
    assert verify_dataset["invalid_item_ids"] == []
    assert report["payload_links"]["status"] == "pass"
    assert report["payload_links"]["payloads"][0]["missing_fields"] == []


def test_verifier_default_does_not_load_observability_or_network(monkeypatch: Any, tmp_path: Path) -> None:
    _write_registry(tmp_path)
    tool = _load_tool(monkeypatch)
    monkeypatch.setitem(sys.modules, "app.services.observability", None)

    report = tool.verify_langfuse_experiments(
        paths=PathConfig(root=tmp_path),
        env={},
        payloads=[_valid_game_payload()],
    )

    assert report["dry_run"] is True
    assert "sync_apply" not in report
    assert "remote_verification" not in report
    assert report["langfuse_config"]["configured"] is False
    assert report["summary"]["warnings"] == 1
    assert report["summary"]["failed"] == 0


def test_dataset_item_id_contract_reports_invalid_plan_item(monkeypatch: Any) -> None:
    tool = _load_tool(monkeypatch)
    plan = [
        {
            "name": "eval-set-a",
            "metadata": {"evaluation_set_id": "eval-set-a"},
            "items": [
                {
                    "item_id": "wrong-item-id",
                    "item_name": "wrong-item-id",
                    "input": {
                        "evaluation_set_id": "eval-set-a",
                        "seed_set_id": "seed-set-a",
                        "seed": 7,
                    },
                    "metadata": {
                        "evaluation_set_id": "eval-set-a",
                        "seed_set_id": "seed-set-a",
                        "seed": 7,
                        "item_name": "wrong-item-id",
                    },
                }
            ],
        }
    ]

    report = tool.verify_dataset_sync_plan(plan)

    assert report["status"] == "fail"
    assert report["invalid_item_ids"][0]["item_id"] == "wrong-item-id"
    assert report["invalid_item_ids"][0]["expected_item_id"] == "eval-set-a:seed-set-a:7"


def test_payload_contract_reports_missing_links_and_bad_item_id(monkeypatch: Any) -> None:
    tool = _load_tool(monkeypatch)
    payload = {
        "games": [
            {
                "game_id": "g-bad",
                "seed": 7,
                "evaluation_set_id": "eval-set-a",
                "seed_set_id": "seed-set-a",
                "langfuse_trace_id": "trace-bad",
                "langfuse_trace_url": "not-a-url",
                "langfuse_dataset_name": "eval-set-a",
                "langfuse_dataset_item_id": "eval-set-a:seed-set-a:8",
            }
        ]
    }

    report = tool.verify_result_payload(payload)

    assert report["status"] == "fail"
    assert "langfuse_dataset_run_id" in report["missing_fields"]
    assert "langfuse_experiment_url" in report["missing_fields"]
    assert report["invalid_urls"][0]["field"] == "langfuse_trace_url"
    assert report["invalid_item_ids"][0]["expected_item_id"] == "eval-set-a:seed-set-a:7"


def test_remote_verification_uses_fake_client_without_env_or_sdk(monkeypatch: Any, tmp_path: Path) -> None:
    _write_registry(tmp_path)
    tool = _load_tool(monkeypatch)
    plan = tool.build_sync_plan(PathConfig(root=tmp_path))
    verify_plan = [dataset for dataset in plan if dataset.name == "verify-contract-v1@v1"]
    item_ids = [item.item_id for item in verify_plan[0].items]
    client = _FakeRemoteClient({dataset.name: [item.item_id for item in dataset.items] for dataset in plan})

    report = tool.verify_langfuse_experiments(
        paths=PathConfig(root=tmp_path),
        env={},
        payloads=[_valid_game_payload()],
        verify_remote=True,
        client=client,
    )

    remote = report["remote_verification"]
    assert remote["status"] == "pass"
    assert remote["checked_dataset_count"] >= 1
    assert "verify-contract-v1@v1" in {call["name"] for call in client.calls}
    assert item_ids
    assert remote["missing_datasets"] == []
    assert remote["missing_items"] == []
    assert client.calls


def test_remote_verification_fail_open_on_client_error(monkeypatch: Any, tmp_path: Path) -> None:
    _write_registry(tmp_path)
    tool = _load_tool(monkeypatch)

    class _FailingClient:
        def get_dataset(self, *args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("langfuse unavailable")

    report = tool.verify_langfuse_experiments(
        paths=PathConfig(root=tmp_path),
        env={},
        payloads=[_valid_game_payload()],
        verify_remote=True,
        client=_FailingClient(),
    )

    remote = report["remote_verification"]
    assert remote["status"] == "fail_open"
    assert "langfuse unavailable" in remote["errors"][0]["error"]
    assert report["summary"]["fail_open"] == 1
