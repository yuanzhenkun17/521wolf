"""Contracts for first-stage benchmark suite specifications.

These tests intentionally exercise the public loader API described in
docs/benchmark-system-plan.md. They are red until the benchmark spec layer is
implemented.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import pytest

from app.config import PathConfig


def _benchmark_spec_module() -> Any:
    try:
        return importlib.import_module("app.lib.benchmark_spec")
    except ModuleNotFoundError as exc:
        pytest.fail(f"missing benchmark spec loader module: {exc.name}")


def _dump_model(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    if isinstance(value, dict):
        return dict(value)
    pytest.fail(f"benchmark spec object is not dumpable: {type(value)!r}")


def _write_spec(root: Path, filename: str, body: str) -> None:
    spec_dir = root / "data" / "benchmarks"
    spec_dir.mkdir(parents=True, exist_ok=True)
    (spec_dir / filename).write_text(body, encoding="utf-8")


def _write_seed_set(root: Path, filename: str, body: str) -> None:
    seed_dir = root / "data" / "benchmark_seed_sets"
    seed_dir.mkdir(parents=True, exist_ok=True)
    (seed_dir / filename).write_text(body, encoding="utf-8")


VALID_ROLE_BASELINE_SPEC = """
id: role-baseline-v1
version: 1
name: Role Baseline Benchmark
description: Fixed-seed role version evaluation benchmark
target_type: role_version
roles:
  - seer
  - witch
game_count: 3
max_days: 5
paired_seed: true
seed_set_id: role-baseline-quick-202606
seed_start: 260600
metrics:
  primary: avg_role_score
  secondary:
    - target_side_win_rate
    - fallback_rate
    - llm_error_rate
    - decision_judge_avg_score
gates:
  min_completed_games: 1
  min_valid_game_rate: 0.5
  max_fallback_rate: 0.5
  max_llm_error_rate: 0.5
judge:
  enable_decision_judge: true
  judge_max_decisions: 10
  judge_concurrency: 2
  judge_timeout_seconds: 60
"""


def test_load_benchmark_spec_reads_first_stage_role_suite(tmp_path: Path) -> None:
    spec_mod = _benchmark_spec_module()
    _write_spec(tmp_path, "role-baseline-v1.yaml", VALID_ROLE_BASELINE_SPEC)

    spec = spec_mod.load_benchmark_spec("role-baseline-v1", paths=PathConfig(root=tmp_path))
    dumped = _dump_model(spec)

    assert dumped["id"] == "role-baseline-v1"
    assert dumped["version"] == 1
    assert dumped["target_type"] == "role_version"
    assert dumped["roles"] == ["seer", "witch"]
    assert dumped["game_count"] == 3
    assert dumped["max_days"] == 5
    assert dumped["paired_seed"] is True
    assert dumped["seed_set_id"] == "role-baseline-quick-202606"
    assert dumped["seed_start"] == 260600
    assert dumped["metrics"]["primary"] == "avg_role_score"
    assert dumped["gates"]["min_completed_games"] == 1
    assert dumped["gates"]["min_valid_game_rate"] == 0.5
    assert dumped["gates"]["max_fallback_rate"] == 0.5
    assert dumped["gates"]["max_llm_error_rate"] == 0.5
    assert dumped["judge"]["enable_decision_judge"] is True
    assert dumped["judge"]["judge_max_decisions"] == 10
    assert dumped["judge"]["judge_concurrency"] == 2
    assert dumped["judge"]["judge_timeout_seconds"] == 60.0


def test_list_benchmark_specs_returns_public_summaries(tmp_path: Path) -> None:
    spec_mod = _benchmark_spec_module()
    _write_spec(tmp_path, "role-baseline-v1.yaml", VALID_ROLE_BASELINE_SPEC)

    specs = spec_mod.list_benchmark_specs(paths=PathConfig(root=tmp_path))
    dumped = [_dump_model(item) for item in specs]
    ids = [item["id"] for item in dumped]

    assert ids[0] == "role-baseline-v1"
    assert {"role-baseline-quick-v1", "role-baseline-standard-v1", "model-baseline-standard-v1"} <= set(ids)
    assert dumped[0]["version"] == 1
    assert dumped[0]["seed_set_id"] == "role-baseline-quick-202606"
    assert specs[0].evaluation_set_id == "role-baseline-v1@v1"


def test_disabled_local_benchmark_spec_blocks_builtin_with_same_id(tmp_path: Path) -> None:
    spec_mod = _benchmark_spec_module()
    _write_spec(
        tmp_path,
        "role-baseline-quick-v1.yaml",
        VALID_ROLE_BASELINE_SPEC.replace("id: role-baseline-v1", "id: role-baseline-quick-v1")
        + "\nenabled: false\n",
    )

    specs = spec_mod.list_benchmark_specs(paths=PathConfig(root=tmp_path))
    ids = {spec.id for spec in specs}

    assert "role-baseline-quick-v1" not in ids
    assert {"role-baseline-standard-v1", "model-baseline-standard-v1"} <= ids


def test_list_benchmark_specs_can_include_inactive_for_management_views(tmp_path: Path) -> None:
    spec_mod = _benchmark_spec_module()
    _write_spec(
        tmp_path,
        "role-baseline-v1.yaml",
        VALID_ROLE_BASELINE_SPEC + "\nstatus: deprecated\n",
    )

    launchable_specs = spec_mod.list_benchmark_specs(paths=PathConfig(root=tmp_path))
    management_specs = spec_mod.list_benchmark_specs(paths=PathConfig(root=tmp_path), include_inactive=True)
    management = {spec.id: spec for spec in management_specs}
    summary = spec_mod.benchmark_spec_summary(management["role-baseline-v1"])

    assert "role-baseline-v1" not in {spec.id for spec in launchable_specs}
    assert management["role-baseline-v1"].lifecycle_status == "deprecated"
    assert management["role-baseline-v1"].launchable is False
    assert summary["status"] == "deprecated"
    assert summary["launchable"] is False
    assert "deprecated" in summary["launch_disabled_reason"]


def test_builtin_benchmark_resources_are_available_without_runtime_data(tmp_path: Path) -> None:
    spec_mod = _benchmark_spec_module()

    specs = spec_mod.list_benchmark_specs(paths=PathConfig(root=tmp_path))
    ids = {spec.id for spec in specs}
    model_spec = spec_mod.load_benchmark_spec("model-baseline-standard-v1", paths=PathConfig(root=tmp_path))
    materialized, seed_set = spec_mod.materialize_benchmark_spec(model_spec, paths=PathConfig(root=tmp_path))
    summary = spec_mod.benchmark_spec_summary(materialized, seed_set)

    assert {"role-baseline-quick-v1", "role-baseline-standard-v1", "model-baseline-standard-v1"} <= ids
    assert materialized.target_type == "model"
    assert materialized.seeds[:3] == [271000, 271011, 271023]
    assert summary["seed_set"]["purpose"] == "model_leaderboard_release"


def test_materialize_benchmark_spec_attaches_seed_registry_snapshot(tmp_path: Path) -> None:
    spec_mod = _benchmark_spec_module()
    _write_spec(tmp_path, "role-baseline-v1.yaml", VALID_ROLE_BASELINE_SPEC)
    _write_seed_set(
        tmp_path,
        "role-baseline-quick-202606.yaml",
        """
id: role-baseline-quick-202606
purpose: role_leaderboard_smoke
version: 1
target_type: role_version
seeds: [260600, 260607, 260619, 260631]
enabled: true
""",
    )

    spec = spec_mod.load_benchmark_spec("role-baseline-v1", paths=PathConfig(root=tmp_path))
    materialized, seed_set = spec_mod.materialize_benchmark_spec(spec, paths=PathConfig(root=tmp_path))
    summary = spec_mod.benchmark_spec_summary(materialized, seed_set)

    assert materialized.seeds == [260600, 260607, 260619]
    assert seed_set.id == "role-baseline-quick-202606"
    assert summary["seed_count"] == 3
    assert summary["seed_preview"] == [260600, 260607, 260619]
    assert summary["seed_set"]["purpose"] == "role_leaderboard_smoke"
    assert summary["seed_set"]["config_hash"].startswith("sha256:")


def test_materialize_benchmark_spec_rejects_seed_set_target_mismatch(tmp_path: Path) -> None:
    spec_mod = _benchmark_spec_module()
    _write_spec(tmp_path, "role-baseline-v1.yaml", VALID_ROLE_BASELINE_SPEC)
    _write_seed_set(
        tmp_path,
        "role-baseline-quick-202606.yaml",
        """
id: role-baseline-quick-202606
target_type: model
seeds: [260600, 260607, 260619]
""",
    )

    spec = spec_mod.load_benchmark_spec("role-baseline-v1", paths=PathConfig(root=tmp_path))

    with pytest.raises(ValueError, match="target_type mismatch"):
        spec_mod.materialize_benchmark_spec(spec, paths=PathConfig(root=tmp_path))


def test_benchmark_config_hash_is_stable_for_equivalent_specs(tmp_path: Path) -> None:
    spec_mod = _benchmark_spec_module()
    _write_spec(tmp_path, "role-baseline-v1.yaml", VALID_ROLE_BASELINE_SPEC)
    _write_spec(
        tmp_path,
        "role-baseline-v1-reordered.yaml",
        """
version: 1
id: role-baseline-v1-reordered
name: Role Baseline Benchmark
description: Fixed-seed role version evaluation benchmark
target_type: role_version
roles: [seer, witch]
game_count: 3
max_days: 5
paired_seed: true
seed_set_id: role-baseline-quick-202606
seed_start: 260600
judge:
  judge_timeout_seconds: 60
  judge_concurrency: 2
  judge_max_decisions: 10
  enable_decision_judge: true
gates:
  max_llm_error_rate: 0.5
  max_fallback_rate: 0.5
  min_valid_game_rate: 0.5
  min_completed_games: 1
metrics:
  secondary:
    - target_side_win_rate
    - fallback_rate
    - llm_error_rate
    - decision_judge_avg_score
  primary: avg_role_score
""",
    )

    spec = spec_mod.load_benchmark_spec("role-baseline-v1", paths=PathConfig(root=tmp_path))
    reordered = spec_mod.load_benchmark_spec("role-baseline-v1-reordered", paths=PathConfig(root=tmp_path))
    reordered = reordered.model_copy(update={"id": "role-baseline-v1"})

    first_hash = spec_mod.benchmark_config_hash(spec)
    second_hash = spec_mod.benchmark_config_hash(reordered)

    assert first_hash.startswith("sha256:")
    assert first_hash == second_hash


def test_load_benchmark_spec_rejects_invalid_role(tmp_path: Path) -> None:
    spec_mod = _benchmark_spec_module()
    _write_spec(
        tmp_path,
        "bad-role.yaml",
        VALID_ROLE_BASELINE_SPEC.replace("id: role-baseline-v1", "id: bad-role").replace(
            "  - witch",
            "  - dragon",
        ),
    )

    with pytest.raises(ValueError, match="unsupported role|dragon"):
        spec_mod.load_benchmark_spec("bad-role", paths=PathConfig(root=tmp_path))
