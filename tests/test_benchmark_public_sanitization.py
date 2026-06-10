"""Public benchmark payload sanitization contracts."""

from __future__ import annotations

import json
from typing import Any

from ui.backend.services.benchmark_leaderboard_payloads import _leaderboard_row_payload
from ui.backend.services.benchmark_report_games import _benchmark_games_for_batch
from ui.backend.services.benchmark_report_payloads import _benchmark_diagnostic_entries, _benchmark_run_report_payload
from ui.backend.services.benchmark_snapshot_payloads import _benchmark_snapshot_compare_payload
from ui.backend.services.benchmark_snapshot_summary_payloads import _benchmark_snapshot_detail_payload


def _leaky_runtime() -> dict[str, Any]:
    return {
        "source": "settings_profile",
        "model_id": "leaky-model",
        "model_config_hash": "leaky_hash",
        "base_url": "https://leak.example/v1?token=hidden-token#fragment-secret",
        "api_key": "sk-public-secret",
        "secret_ref": "secret-ref-value",
        "endpoint_url": "https://inner.example/v1?api_key=inner-hidden",
        "hash_input": {
            "base_url": "https://hash.example/v1?token=hash-hidden",
            "metadata": {
                "token": "nested-hidden-token",
                "visible": "kept",
            },
        },
    }


def _dirty_leaderboard_row() -> dict[str, Any]:
    runtime = _leaky_runtime()
    return {
        "scope": "model",
        "subject_id": "leaky_hash",
        "model_id": "leaky-model",
        "model_config_hash": "leaky_hash",
        "comparison_group_id": "bench_leaky",
        "evaluation_set_id": "model-baseline-v1@v1",
        "seed_set_id": "model-baseline-quick-202606",
        "games_played": 30,
        "valid_game_rate": 1.0,
        "strength_score": 6.8,
        "avg_role_score": 6.5,
        "fallback_rate": 0.02,
        "llm_error_rate": 0.01,
        "policy_adjusted_rate": 0.0,
        "target_side_win_rate": 0.55,
        "rankable": True,
        "data_sufficient": True,
        "summary": json.dumps(
            {
                "source_run_id": "bench_leaky",
                "result_batch_id": "bench_leaky_model",
                "model_runtime": runtime,
                "config": {"model_runtime": runtime},
            },
            ensure_ascii=False,
        ),
        "model_runtime": runtime,
        "updated_at": "2026-06-10T10:00:00+08:00",
    }


def _assert_no_runtime_secrets(value: Any) -> None:
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True)
    for forbidden in (
        "sk-public-secret",
        "sk-game-secret123",
        "secret-ref-value",
        "hidden-token",
        "fragment-secret",
        "diag-hidden",
        "diag-url-hidden",
        "warn-hidden",
        "err-hidden",
        "result-bearer-secret",
        "result-url-hidden",
        "game-hidden",
        "trace-hidden",
        "run-hidden",
        "inner-hidden",
        "hash-hidden",
        "nested-hidden-token",
    ):
        assert forbidden not in serialized


def test_leaderboard_row_sanitizes_model_runtime_from_summary_and_row() -> None:
    payload = _leaderboard_row_payload(_dirty_leaderboard_row())

    assert payload["model_runtime"]["base_url"] == "https://leak.example/v1"
    assert payload["model_runtime"]["endpoint_url"] == "https://inner.example/v1"
    assert payload["summary"]["config"]["model_runtime"]["hash_input"]["base_url"] == "https://hash.example/v1"
    _assert_no_runtime_secrets(payload)


def test_snapshot_detail_and_compare_sanitize_frozen_model_runtime_rows() -> None:
    dirty_row = {
        **_leaderboard_row_payload(_dirty_leaderboard_row()),
        "model_runtime": _leaky_runtime(),
        "summary": {"model_runtime": _leaky_runtime(), "config": {"model_runtime": _leaky_runtime()}},
    }
    snapshot = {
        "snapshot_id": "bench_snap_leaky",
        "schema_version": 1,
        "scope": "model",
        "evaluation_set_id": "model-baseline-v1@v1",
        "summary": {"model_runtime": _leaky_runtime(), "row_count": 1},
        "rows": [dirty_row],
        "row_count": 1,
        "created_at": "2026-06-10T10:00:00+08:00",
    }

    detail = _benchmark_snapshot_detail_payload(snapshot)
    compare = _benchmark_snapshot_compare_payload(
        snapshot,
        [dirty_row],
        [dirty_row],
        scope="model",
        evaluation_set_id="model-baseline-v1@v1",
        target_role=None,
    )

    assert detail["summary"]["model_runtime"]["base_url"] == "https://leak.example/v1"
    assert detail["rows"][0]["model_runtime"]["endpoint_url"] == "https://inner.example/v1"
    assert compare["current"]["rows"][0]["model_runtime"]["base_url"] == "https://leak.example/v1"
    assert compare["frozen"]["rows"][0]["summary"]["config"]["model_runtime"]["endpoint_url"] == "https://inner.example/v1"
    _assert_no_runtime_secrets({"detail": detail, "compare": compare})


def test_benchmark_games_and_diagnostics_sanitize_raw_text_and_urls() -> None:
    batch = {
        "batch_id": "bench_public_sanitize",
        "status": "completed",
        "target_type": "model",
        "config": {"benchmark_id": "model-baseline-v1", "evaluation_set_id": "model-baseline-v1@v1"},
        "diagnostics": [
            {
                "kind": "batch_warning",
                "message": "batch api_key=diag-hidden",
                "details_url": "https://diag.example/log?token=diag-url-hidden#fragment-secret",
            }
        ],
        "results": [
            {
                "batch_id": "bench_public_sanitize_model",
                "config": {"batch_id": "bench_public_sanitize_model", "comparison_group_id": "bench_public_sanitize"},
                "game_count": 1,
                "completed": 1,
                "errored": 0,
                "rankable": True,
                "warnings": ["warning token=warn-hidden"],
                "errors": ["error api_key=err-hidden"],
                "diagnostics": [
                    {
                        "kind": "result_warning",
                        "message": "Bearer result-bearer-secret",
                        "evidence_url": "https://evidence.example/path?api_key=result-url-hidden",
                    }
                ],
                "games": [
                    {
                        "game_id": "game-public-sanitize",
                        "status": "failed",
                        "seed": 270600,
                        "error": "sk-game-secret123 token=game-hidden",
                        "langfuse": {
                            "trace_id": "trace-1",
                            "trace_url": "https://langfuse.example/trace?token=trace-hidden#fragment-secret",
                            "dataset_run_url": "https://langfuse.example/run?api_key=run-hidden",
                        },
                        "diagnostics": [
                            {
                                "kind": "game_warning",
                                "message": "game token=game-hidden",
                                "trace_url": "https://diag.example/game?token=trace-hidden",
                            }
                        ],
                    }
                ],
            }
        ],
    }

    games = _benchmark_games_for_batch(batch)
    diagnostics = _benchmark_diagnostic_entries(batch)
    report = _benchmark_run_report_payload(batch)

    assert "[REDACTED]" in games[0]["error"]
    assert games[0]["langfuse"]["trace_url"] == "https://langfuse.example/trace"
    assert games[0]["langfuse"]["dataset_run_url"] == "https://langfuse.example/run"
    assert any(item.get("details_url") == "https://diag.example/log" for item in diagnostics)
    assert any(item.get("evidence_url") == "https://evidence.example/path" for item in diagnostics)
    assert any(item.get("trace_url") == "https://diag.example/game" for item in diagnostics)
    _assert_no_runtime_secrets({"games": games, "diagnostics": diagnostics, "report": report})
