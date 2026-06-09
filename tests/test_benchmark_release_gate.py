from __future__ import annotations

from typing import Any

from app.lib.benchmark_release_gate import evaluate_benchmark_release_gate


def _request(**overrides: Any) -> dict[str, Any]:
    request = {
        "snapshot_id": "snapshot-release-a",
        "scope": "model",
        "benchmark_id": "model-baseline-v1",
        "evaluation_set_id": "model-baseline-v1@v1",
        "seed_set_id": "model-baseline-quick-202606",
        "benchmark_config_hash": "sha256:model-contract",
    }
    request.update(overrides)
    return request


def _row(**overrides: Any) -> dict[str, Any]:
    row = {
        "scope": "model",
        "subject_id": "runtime_hash_v1",
        "model_id": "qwen-max",
        "model_config_hash": "runtime_hash_v1",
        "evaluation_set_id": "model-baseline-v1@v1",
        "seed_set_id": "model-baseline-quick-202606",
        "benchmark_config_hash": "sha256:model-contract",
        "sample_size": 12,
        "completed_games": 12,
        "paired_sample_size": 8,
        "source_run_id": "bench_release_run_a",
        "result_batch_id": "bench_release_run_a_qwen_max",
        "report_id": "benchmark_report:bench_release_run_a",
        "diagnostics": [],
    }
    row.update(overrides)
    return row


def _config(**overrides: Any) -> dict[str, Any]:
    config = {
        "suite_lifecycle": {"status": "enabled", "launchable": True},
        "thresholds": {
            "min_sample_size": 10,
            "min_completed_games": 10,
            "min_paired_overlap": 6,
            "blocking_diagnostic_levels": ["error", "critical", "fatal"],
            "warning_diagnostic_levels": ["warning"],
        },
    }
    config.update(overrides)
    return config


def _codes(payload: dict[str, Any]) -> set[str]:
    return {item["code"] for item in payload["blockers"]}


def _warning_codes(payload: dict[str, Any]) -> set[str]:
    return {item["code"] for item in payload["warnings"]}


def _assert_issue_shape(issue: dict[str, Any]) -> None:
    assert set(issue) == {"code", "severity", "message", "evidence", "affected_ids"}
    assert isinstance(issue["code"], str) and issue["code"]
    assert issue["severity"] in {"error", "warning"}
    assert isinstance(issue["message"], str) and issue["message"]
    assert isinstance(issue["evidence"], dict)
    assert isinstance(issue["affected_ids"], list)
    assert issue["affected_ids"]


def test_benchmark_release_gate_allows_complete_release_payload() -> None:
    payload = evaluate_benchmark_release_gate(
        request=_request(),
        rows=[_row()],
        config=_config(),
    )

    assert payload["ok"] is True
    assert payload["blockers"] == []
    assert payload["warnings"] == []
    assert payload["summary"]["scope"] == "model"
    assert payload["summary"]["benchmark_config_hash"] == "sha256:model-contract"
    assert payload["summary"]["row_count"] == 1
    assert payload["summary"]["suite_lifecycle"]["launchable"] is True
    assert payload["summary"]["rows"][0]["sample_size"] == 12
    assert payload["summary"]["rows"][0]["paired_overlap"] == 8


def test_benchmark_release_gate_blocks_non_launchable_suite_lifecycle() -> None:
    payload = evaluate_benchmark_release_gate(
        request=_request(),
        rows=[_row()],
        config=_config(suite_lifecycle={"status": "deprecated", "launchable": False}),
    )

    assert payload["ok"] is False
    assert "suite_not_launchable" in _codes(payload)
    blocker = next(item for item in payload["blockers"] if item["code"] == "suite_not_launchable")
    _assert_issue_shape(blocker)
    assert blocker["evidence"]["status"] == "deprecated"
    assert blocker["evidence"]["launchable"] is False


def test_benchmark_release_gate_blocks_insufficient_sample_and_completed_games() -> None:
    payload = evaluate_benchmark_release_gate(
        request=_request(),
        rows=[_row(sample_size=7, completed_games=6)],
        config=_config(),
    )

    assert {
        "sample_size_below_minimum",
        "completed_games_below_minimum",
    }.issubset(_codes(payload))
    for blocker in payload["blockers"]:
        _assert_issue_shape(blocker)
    sample_blocker = next(item for item in payload["blockers"] if item["code"] == "sample_size_below_minimum")
    assert sample_blocker["evidence"]["sample_size"] == 7
    assert sample_blocker["evidence"]["min_sample_size"] == 10
    completed_blocker = next(
        item for item in payload["blockers"] if item["code"] == "completed_games_below_minimum"
    )
    assert completed_blocker["evidence"]["completed_games"] == 6
    assert completed_blocker["evidence"]["min_completed_games"] == 10


def test_benchmark_release_gate_blocks_insufficient_paired_overlap() -> None:
    payload = evaluate_benchmark_release_gate(
        request=_request(),
        rows=[_row(paired_sample_size=3)],
        config=_config(),
    )

    assert "paired_overlap_below_minimum" in _codes(payload)
    blocker = next(item for item in payload["blockers"] if item["code"] == "paired_overlap_below_minimum")
    _assert_issue_shape(blocker)
    assert blocker["evidence"]["paired_overlap"] == 3
    assert blocker["evidence"]["min_paired_overlap"] == 6


def test_benchmark_release_gate_blocks_blocking_diagnostic_severity_and_warns_for_warning() -> None:
    payload = evaluate_benchmark_release_gate(
        request=_request(diagnostics=[{"kind": "release_note_missing", "level": "warning"}]),
        rows=[
            _row(
                diagnostics=[
                    {
                        "kind": "leaderboard_gate_failed",
                        "level": "error",
                        "message": "rankable gate failed",
                        "game_id": "game-a",
                    }
                ]
            )
        ],
        config=_config(),
    )

    assert "diagnostic_severity_blocked" in _codes(payload)
    assert "diagnostic_warning_present" in _warning_codes(payload)
    blocker = next(item for item in payload["blockers"] if item["code"] == "diagnostic_severity_blocked")
    warning = next(item for item in payload["warnings"] if item["code"] == "diagnostic_warning_present")
    _assert_issue_shape(blocker)
    _assert_issue_shape(warning)
    assert blocker["evidence"]["kind"] == "leaderboard_gate_failed"
    assert blocker["evidence"]["level"] == "error"
    assert "game-a" in blocker["affected_ids"]
    assert warning["evidence"]["kind"] == "release_note_missing"
    assert warning["evidence"]["origin"] == "release"
    assert payload["summary"]["diagnostics"]["by_level"] == {"error": 1, "warning": 1}


def test_benchmark_release_gate_blocks_benchmark_hash_and_row_scope_mismatch() -> None:
    payload = evaluate_benchmark_release_gate(
        request=_request(scope="model", benchmark_config_hash="sha256:model-contract"),
        rows=[_row(scope="role_version", benchmark_config_hash="sha256:other-contract")],
        config=_config(),
    )

    assert {"row_scope_mismatch", "benchmark_config_hash_mismatch"}.issubset(_codes(payload))
    scope_blocker = next(item for item in payload["blockers"] if item["code"] == "row_scope_mismatch")
    hash_blocker = next(item for item in payload["blockers"] if item["code"] == "benchmark_config_hash_mismatch")
    _assert_issue_shape(scope_blocker)
    _assert_issue_shape(hash_blocker)
    assert scope_blocker["evidence"] == {"row_index": 0, "expected": "model", "actual": "role_version"}
    assert hash_blocker["evidence"]["expected"] == "sha256:model-contract"
    assert hash_blocker["evidence"]["actual"] == "sha256:other-contract"


def test_benchmark_release_gate_blocks_model_scope_without_model_config_hash() -> None:
    payload = evaluate_benchmark_release_gate(
        request=_request(scope="model"),
        rows=[_row(model_config_hash="")],
        config=_config(),
    )

    assert "model_config_hash_missing" in _codes(payload)
    blocker = next(item for item in payload["blockers"] if item["code"] == "model_config_hash_missing")
    _assert_issue_shape(blocker)
    assert blocker["evidence"]["scope"] == "model"


def test_benchmark_release_gate_blocks_missing_source_links() -> None:
    payload = evaluate_benchmark_release_gate(
        request=_request(),
        rows=[_row(source_run_id="", result_batch_id="", report_id="")],
        config=_config(),
    )

    assert {
        "source_run_id_missing",
        "result_batch_id_missing",
        "report_id_missing",
    }.issubset(_codes(payload))
    for blocker in payload["blockers"]:
        _assert_issue_shape(blocker)
    assert payload["summary"]["rows"][0]["source_run_id"] == ""
    assert payload["summary"]["rows"][0]["result_batch_id"] == ""
    assert payload["summary"]["rows"][0]["report_id"] == ""


def test_benchmark_release_gate_blocks_missing_global_and_row_boundaries() -> None:
    payload = evaluate_benchmark_release_gate(
        request=_request(scope="", benchmark_config_hash=""),
        rows=[_row(scope="", benchmark_config_hash="")],
        config=_config(),
    )

    assert {
        "scope_missing",
        "benchmark_config_hash_missing",
        "row_scope_missing",
        "row_benchmark_config_hash_missing",
    }.issubset(_codes(payload))
    for blocker in payload["blockers"]:
        _assert_issue_shape(blocker)
