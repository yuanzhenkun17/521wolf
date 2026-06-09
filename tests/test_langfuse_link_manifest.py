from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from typing import Any

from app.tools.build_langfuse_link_manifest import build_link_manifest, main


def _benchmark_payload() -> dict[str, Any]:
    return {
        "kind": "benchmark_batch_detail",
        "batch_id": "bench_manifest",
        "benchmark": {
            "id": "role-baseline-v1",
            "version": 1,
            "evaluation_set_id": "role-baseline-v1@v1",
            "seed_set_id": "role-baseline-quick",
            "target_type": "role_version",
        },
        "results": [
            {
                "batch_id": "bench_manifest_seer",
                "result_batch_id": "bench_manifest_seer",
                "config": {"target_role": "seer", "target_version_id": "seer_candidate_v2"},
                "games": [
                    {
                        "game_id": "bench_manifest_game_001",
                        "seed": 260600,
                        "langfuse": {
                            "trace_id": "trace-game-001",
                            "trace_url": "http://langfuse.local/project/p/traces/trace-game-001",
                            "experiment_url": "http://langfuse.local/project/p/datasets/d/runs/r-001",
                        },
                        "private_reasoning": "PRIVATE_REASONING_SHOULD_NOT_APPEAR",
                        "prompt": "PROMPT_SHOULD_NOT_APPEAR",
                        "raw_messages": [{"role": "user", "content": "RAW_MESSAGES_SHOULD_NOT_APPEAR"}],
                        "raw_output": "RAW_OUTPUT_SHOULD_NOT_APPEAR",
                        "completion": "COMPLETION_SHOULD_NOT_APPEAR",
                    }
                ],
            }
        ],
    }


def test_build_link_manifest_extracts_nested_langfuse_links_and_local_link() -> None:
    manifest = build_link_manifest([_benchmark_payload()], ui_base_url="http://localhost:5173")

    game_item = next(item for item in manifest["items"] if item["game_id"] == "bench_manifest_game_001")
    assert manifest["schema_version"] == "langfuse_link_manifest_v1"
    assert game_item["source_type"] == "benchmark"
    assert game_item["batch_id"] == "bench_manifest"
    assert game_item["result_batch_id"] == "bench_manifest_seer"
    assert game_item["seed"] == 260600
    assert game_item["trace_id"] == "trace-game-001"
    assert game_item["trace_url"] == "http://langfuse.local/project/p/traces/trace-game-001"
    assert game_item["experiment_url"] == "http://langfuse.local/project/p/datasets/d/runs/r-001"
    assert game_item["local_url"] == (
        "http://localhost:5173/benchmark/batch/bench_manifest/games?game_id=bench_manifest_game_001"
    )
    assert game_item["ui_deep_link"] == game_item["local_url"]
    assert game_item["metadata"]["benchmark_id"] == "role-baseline-v1"
    assert game_item["metadata"]["target_role"] == "seer"
    assert manifest["missing_links"] == []


def test_missing_trace_url_is_reported_without_failing() -> None:
    payload = {
        "kind": "eval_result",
        "batch_id": "eval_batch",
        "games": [
            {
                "game_id": "eval_game_001",
                "seed": 7,
                "trace_id": "trace-no-url",
            }
        ],
    }

    manifest = build_link_manifest([payload], ui_base_url="http://localhost:5173")

    game_item = next(item for item in manifest["items"] if item["game_id"] == "eval_game_001")
    missing = next(row for row in manifest["missing_links"] if row["id"] == game_item["id"])
    assert game_item["trace_id"] == "trace-no-url"
    assert game_item["trace_url"] is None
    assert "missing_trace_url_for_trace_id" in missing["reasons"]
    assert "missing_langfuse_url" in missing["reasons"]
    assert missing["trace_id"] == "trace-no-url"


def test_annotation_queue_payload_metadata_links_are_read() -> None:
    payload = {
        "schema_version": "langfuse_annotation_queue_export_v1",
        "item_count": 1,
        "items": [
            {
                "id": "annotation:item-001",
                "priority_score": 100,
                "metadata": {
                    "annotation_scope": "game",
                    "game_id": "queue_game_001",
                    "batch_id": "queue_batch",
                    "result_batch_id": "queue_batch_seer",
                    "seed": 11,
                    "trace_id": "trace-queue-001",
                    "trace_url": "http://langfuse.local/project/p/traces/trace-queue-001",
                    "experiment_url": "http://langfuse.local/project/p/datasets/d/runs/r-queue",
                    "ui_deep_link": "http://localhost:5173/benchmark/batch/queue_batch/games?game_id=queue_game_001",
                },
                "annotation_task": {"type": "human_annotation"},
            }
        ],
    }

    manifest = build_link_manifest([payload])

    assert manifest["item_count"] == 1
    item = manifest["items"][0]
    assert item["source_type"] == "annotation_queue"
    assert item["game_id"] == "queue_game_001"
    assert item["trace_id"] == "trace-queue-001"
    assert item["local_url"] == "http://localhost:5173/benchmark/batch/queue_batch/games?game_id=queue_game_001"
    assert item["metadata"]["annotation_scope"] == "game"


def test_main_writes_manifest_file_without_constructing_clients(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    fake_observability = types.ModuleType("app.services.observability")
    fake_observability.get_langfuse_client = lambda: (_ for _ in ()).throw(
        AssertionError("manifest builder must stay offline")
    )
    monkeypatch.setitem(sys.modules, "app.services.observability", fake_observability)

    input_path = tmp_path / "payload.json"
    output_path = tmp_path / "manifest.json"
    input_path.write_text(json.dumps(_benchmark_payload()), encoding="utf-8")

    exit_code = main([str(input_path), "-o", str(output_path), "--ui-base-url", "http://localhost:5173"])

    written = json.loads(output_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert written["schema_version"] == "langfuse_link_manifest_v1"
    assert any(item["trace_id"] == "trace-game-001" for item in written["items"])


def test_manifest_does_not_emit_sensitive_text() -> None:
    manifest = build_link_manifest([_benchmark_payload()])
    serialized = json.dumps(manifest, ensure_ascii=False)

    assert "PRIVATE_REASONING_SHOULD_NOT_APPEAR" not in serialized
    assert "PROMPT_SHOULD_NOT_APPEAR" not in serialized
    assert "RAW_MESSAGES_SHOULD_NOT_APPEAR" not in serialized
    assert "RAW_OUTPUT_SHOULD_NOT_APPEAR" not in serialized
    assert "COMPLETION_SHOULD_NOT_APPEAR" not in serialized
