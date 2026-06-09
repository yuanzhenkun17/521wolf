"""Benchmark spec loading and hashing.

Benchmark specs are versioned evaluation protocols.  They are intentionally
loaded outside the UI layer so app code, API code, and tests can share the same
validation and stable config hashing.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.config import DEFAULT_PATHS, PathConfig
from engine.models import Role


VALID_BENCHMARK_TARGET_TYPES = {"role_version", "model"}
VALID_BENCHMARK_ROLES = {role.value for role in Role}
VALID_BENCHMARK_STATUSES = {"enabled", "active", "draft", "deprecated", "disabled", "archived"}
LAUNCHABLE_BENCHMARK_STATUSES = {"enabled", "active"}
_BUILTIN_RESOURCES_DIR = Path(__file__).resolve().parents[1] / "resources"


class BenchmarkSpecError(ValueError):
    """Raised when a benchmark spec cannot be loaded or validated."""


class BenchmarkMetrics(BaseModel):
    primary: str = "avg_role_score"
    secondary: list[str] = Field(default_factory=list)


class BenchmarkGates(BaseModel):
    min_completed_games: int = Field(default=1, ge=0, le=200)
    min_valid_game_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    max_fallback_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    max_llm_error_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    max_policy_adjusted_rate: float | None = Field(default=None, ge=0.0, le=1.0)


class BenchmarkJudgeConfig(BaseModel):
    enable_decision_judge: bool = False
    judge_max_decisions: int | None = Field(default=None, ge=0, le=500)
    judge_concurrency: int | None = Field(default=None, ge=1, le=64)
    judge_timeout_seconds: float | None = Field(default=None, ge=1.0, le=3600.0)


class BenchmarkSeedSet(BaseModel):
    id: str = Field(min_length=1)
    purpose: str = ""
    version: int = Field(default=1, ge=1)
    description: str = ""
    target_type: Literal["role_version", "model"] | None = None
    seeds: list[int] = Field(default_factory=list)
    enabled: bool = True

    @field_validator("id")
    @classmethod
    def normalize_id(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("seed set id is required")
        return text

    @field_validator("seeds")
    @classmethod
    def normalize_seeds(cls, value: list[int]) -> list[int]:
        seeds: list[int] = []
        seen: set[int] = set()
        for item in value:
            seed = int(item)
            if seed < 0:
                raise ValueError("benchmark seed must be non-negative")
            if seed in seen:
                continue
            seen.add(seed)
            seeds.append(seed)
        if not seeds:
            raise ValueError("seed set must include at least one seed")
        return seeds


class BenchmarkSpec(BaseModel):
    id: str = Field(min_length=1)
    version: int = Field(ge=1)
    name: str = ""
    description: str = ""
    target_type: Literal["role_version", "model"] = "role_version"
    roles: list[str] = Field(default_factory=list)
    game_count: int = Field(ge=0, le=200)
    max_days: int = Field(ge=1, le=100)
    paired_seed: bool = True
    seed_set_id: str = Field(min_length=1)
    seed_start: int = 0
    seeds: list[int] | None = None
    metrics: BenchmarkMetrics = Field(default_factory=BenchmarkMetrics)
    gates: BenchmarkGates = Field(default_factory=BenchmarkGates)
    judge: BenchmarkJudgeConfig = Field(default_factory=BenchmarkJudgeConfig)
    enabled: bool = True
    status: str = ""
    cost_tier: str = "standard"

    @field_validator("id")
    @classmethod
    def normalize_id(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("benchmark id is required")
        return text

    @field_validator("roles")
    @classmethod
    def normalize_roles(cls, value: list[str]) -> list[str]:
        roles: list[str] = []
        seen: set[str] = set()
        for item in value:
            role = str(item or "").strip().lower()
            if not role:
                continue
            if role not in VALID_BENCHMARK_ROLES:
                raise ValueError(f"unsupported benchmark role: {role}")
            if role in seen:
                continue
            seen.add(role)
            roles.append(role)
        if not roles:
            raise ValueError("benchmark spec must include at least one role")
        return roles

    @field_validator("status")
    @classmethod
    def normalize_status(cls, value: str) -> str:
        status = str(value or "").strip().lower()
        if not status:
            return ""
        if status not in VALID_BENCHMARK_STATUSES:
            raise ValueError(f"unsupported benchmark status: {status}")
        return status

    @field_validator("seeds")
    @classmethod
    def normalize_explicit_seeds(cls, value: list[int] | None) -> list[int] | None:
        if value is None:
            return None
        seeds: list[int] = []
        seen: set[int] = set()
        for item in value:
            seed = int(item)
            if seed < 0:
                raise ValueError("benchmark seed must be non-negative")
            if seed in seen:
                continue
            seen.add(seed)
            seeds.append(seed)
        if not seeds:
            raise ValueError("explicit benchmark seeds cannot be empty")
        return seeds

    @model_validator(mode="after")
    def validate_seed_count(self) -> "BenchmarkSpec":
        if self.seeds is not None and len(self.seeds) < self.game_count:
            raise ValueError("explicit benchmark seeds must cover game_count")
        return self

    @property
    def evaluation_set_id(self) -> str:
        return f"{self.id}@v{self.version}"

    @property
    def lifecycle_status(self) -> str:
        if not self.enabled and self.status in {"", "enabled", "active"}:
            return "disabled"
        if self.status:
            return self.status
        return "enabled" if self.enabled else "disabled"

    @property
    def launchable(self) -> bool:
        return self.lifecycle_status in LAUNCHABLE_BENCHMARK_STATUSES


def benchmarks_dir(paths: PathConfig | None = None) -> Path:
    resolved = paths or DEFAULT_PATHS
    return Path(resolved.data_dir) / "benchmarks"


def benchmark_seed_sets_dir(paths: PathConfig | None = None) -> Path:
    resolved = paths or DEFAULT_PATHS
    return Path(resolved.data_dir) / "benchmark_seed_sets"


def builtin_benchmarks_dir() -> Path:
    return _BUILTIN_RESOURCES_DIR / "benchmarks"


def builtin_benchmark_seed_sets_dir() -> Path:
    return _BUILTIN_RESOURCES_DIR / "benchmark_seed_sets"


def list_benchmark_specs(paths: PathConfig | None = None, *, include_inactive: bool = False) -> list[BenchmarkSpec]:
    """Load every enabled benchmark spec from the configured data directory."""
    specs: list[BenchmarkSpec] = []
    seen_ids: set[str] = set()
    for candidate_root in _candidate_benchmark_dirs(paths):
        if not candidate_root.exists():
            continue
        for path in sorted(candidate_root.iterdir(), key=lambda item: item.name):
            if path.suffix.lower() not in {".json", ".yaml", ".yml"}:
                continue
            spec = _load_spec_path(path)
            if spec.id in seen_ids:
                continue
            seen_ids.add(spec.id)
            if include_inactive or spec.launchable:
                specs.append(spec)
    return specs


def load_benchmark_spec(benchmark_id: str, paths: PathConfig | None = None) -> BenchmarkSpec:
    """Load a benchmark spec by id."""
    wanted = str(benchmark_id or "").strip()
    if not wanted:
        raise BenchmarkSpecError("benchmark_id is required")
    for root in _candidate_benchmark_dirs(paths):
        candidates = [
            root / f"{wanted}.json",
            root / f"{wanted}.yaml",
            root / f"{wanted}.yml",
        ]
        for path in candidates:
            if path.exists():
                return _load_spec_path(path)
    for spec in list_benchmark_specs(paths):
        if spec.id == wanted:
            return spec
    raise BenchmarkSpecError(f"benchmark spec not found: {wanted}")


def list_benchmark_seed_sets(paths: PathConfig | None = None) -> list[BenchmarkSeedSet]:
    """Load every enabled benchmark seed set from the configured registry."""
    seed_sets: list[BenchmarkSeedSet] = []
    seen_ids: set[str] = set()
    for candidate_root in _candidate_seed_set_dirs(paths):
        if not candidate_root.exists():
            continue
        for path in sorted(candidate_root.iterdir(), key=lambda item: item.name):
            if path.suffix.lower() not in {".json", ".yaml", ".yml"}:
                continue
            seed_set = _load_seed_set_path(path)
            if seed_set.id in seen_ids:
                continue
            seen_ids.add(seed_set.id)
            if seed_set.enabled:
                seed_sets.append(seed_set)
    return seed_sets


def load_benchmark_seed_set(seed_set_id: str, paths: PathConfig | None = None) -> BenchmarkSeedSet:
    """Load a benchmark seed set by id."""
    wanted = str(seed_set_id or "").strip()
    if not wanted:
        raise BenchmarkSpecError("seed_set_id is required")
    for root in _candidate_seed_set_dirs(paths):
        candidates = [
            root / f"{wanted}.json",
            root / f"{wanted}.yaml",
            root / f"{wanted}.yml",
        ]
        for path in candidates:
            if path.exists():
                return _load_seed_set_path(path)
    for seed_set in list_benchmark_seed_sets(paths):
        if seed_set.id == wanted:
            return seed_set
    raise BenchmarkSpecError(f"benchmark seed set not found: {wanted}")


def _candidate_benchmark_dirs(paths: PathConfig | None = None) -> list[Path]:
    primary = benchmarks_dir(paths)
    candidates = [primary, builtin_benchmarks_dir()]
    fallback = benchmarks_dir(DEFAULT_PATHS)
    if primary != fallback:
        candidates.append(fallback)
    return _unique_paths(candidates)


def _candidate_seed_set_dirs(paths: PathConfig | None = None) -> list[Path]:
    primary = benchmark_seed_sets_dir(paths)
    candidates = [primary, builtin_benchmark_seed_sets_dir()]
    fallback = benchmark_seed_sets_dir(DEFAULT_PATHS)
    if primary != fallback:
        candidates.append(fallback)
    return _unique_paths(candidates)


def _unique_paths(paths: list[Path]) -> list[Path]:
    result: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path.resolve()) if path.exists() else str(path)
        if key in seen:
            continue
        seen.add(key)
        result.append(path)
    return result


def benchmark_config_hash(spec: BenchmarkSpec | dict[str, Any]) -> str:
    """Return a stable hash for a benchmark spec or spec snapshot."""
    if isinstance(spec, BenchmarkSpec):
        payload = spec.model_dump(mode="json")
    else:
        payload = dict(spec)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


def seed_set_config_hash(seed_set: BenchmarkSeedSet | dict[str, Any]) -> str:
    """Return a stable hash for a seed set or seed-set snapshot."""
    if isinstance(seed_set, BenchmarkSeedSet):
        payload = seed_set.model_dump(mode="json")
    else:
        payload = dict(seed_set)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


def benchmark_seed_set_summary(seed_set: BenchmarkSeedSet) -> dict[str, Any]:
    seeds = list(seed_set.seeds)
    return {
        "id": seed_set.id,
        "purpose": seed_set.purpose,
        "version": seed_set.version,
        "description": seed_set.description,
        "target_type": seed_set.target_type,
        "seed_count": len(seeds),
        "seed_preview": seeds[:5],
        "config_hash": seed_set_config_hash(seed_set),
        "enabled": seed_set.enabled,
    }


def benchmark_spec_summary(spec: BenchmarkSpec, seed_set: BenchmarkSeedSet | None = None) -> dict[str, Any]:
    """Small API-safe spec summary."""
    seeds = _spec_seeds(spec, seed_set)
    lifecycle_status = spec.lifecycle_status
    launchable = spec.launchable
    return {
        "id": spec.id,
        "version": spec.version,
        "name": spec.name,
        "description": spec.description,
        "target_type": spec.target_type,
        "roles": list(spec.roles),
        "game_count": spec.game_count,
        "max_days": spec.max_days,
        "paired_seed": spec.paired_seed,
        "seed_set_id": spec.seed_set_id,
        "seed_start": spec.seed_start,
        "seed_count": len(seeds) if seeds is not None else spec.game_count,
        "seed_preview": seeds[:5] if seeds is not None else [spec.seed_start + index for index in range(min(spec.game_count, 5))],
        "evaluation_set_id": spec.evaluation_set_id,
        "metrics": spec.metrics.model_dump(mode="json"),
        "gates": spec.gates.model_dump(mode="json"),
        "judge": spec.judge.model_dump(mode="json"),
        "config_hash": benchmark_config_hash(spec),
        "seed_set": benchmark_seed_set_summary(seed_set) if seed_set is not None else None,
        "enabled": spec.enabled,
        "status": lifecycle_status,
        "launchable": launchable,
        "launch_disabled_reason": "" if launchable else benchmark_spec_launch_disabled_reason(spec),
        "cost_tier": spec.cost_tier,
    }


def benchmark_spec_launch_disabled_reason(spec: BenchmarkSpec) -> str:
    """Return the product-facing reason a benchmark suite cannot be launched."""
    status = spec.lifecycle_status
    if status in LAUNCHABLE_BENCHMARK_STATUSES:
        return ""
    reasons = {
        "draft": "benchmark suite is draft and must be enabled before launch",
        "deprecated": "benchmark suite is deprecated and cannot be launched",
        "disabled": "benchmark suite is disabled and cannot be launched",
        "archived": "benchmark suite is archived and cannot be launched",
    }
    return reasons.get(status, f"benchmark suite status={status} cannot be launched")


def materialize_benchmark_spec(
    spec: BenchmarkSpec,
    *,
    paths: PathConfig | None = None,
) -> tuple[BenchmarkSpec, BenchmarkSeedSet | None]:
    """Attach explicit registry seeds to a spec when the referenced seed set exists."""
    try:
        seed_set = load_benchmark_seed_set(spec.seed_set_id, paths)
    except BenchmarkSpecError as exc:
        if "not found" not in str(exc):
            raise
        return spec, None
    if seed_set.target_type and seed_set.target_type != spec.target_type:
        raise BenchmarkSpecError(
            f"benchmark seed set target_type mismatch: {seed_set.id} is {seed_set.target_type}, "
            f"spec is {spec.target_type}"
        )
    if len(seed_set.seeds) < spec.game_count:
        raise BenchmarkSpecError(
            f"benchmark seed set {seed_set.id} has {len(seed_set.seeds)} seeds, "
            f"requires at least {spec.game_count}"
        )
    return spec.model_copy(update={"seeds": list(seed_set.seeds[: spec.game_count])}), seed_set


def _spec_seeds(spec: BenchmarkSpec, seed_set: BenchmarkSeedSet | None = None) -> list[int] | None:
    if spec.seeds is not None:
        return list(spec.seeds[: spec.game_count])
    if seed_set is not None:
        return list(seed_set.seeds[: spec.game_count])
    return None


def _load_spec_path(path: Path) -> BenchmarkSpec:
    try:
        raw = _read_structured_file(path)
        if not isinstance(raw, dict):
            raise BenchmarkSpecError(f"benchmark spec must be an object: {path}")
        return BenchmarkSpec.model_validate(raw)
    except BenchmarkSpecError:
        raise
    except Exception as exc:  # noqa: BLE001 - normalize loader failures
        raise BenchmarkSpecError(f"failed to load benchmark spec {path}: {exc}") from exc


def _load_seed_set_path(path: Path) -> BenchmarkSeedSet:
    try:
        raw = _read_structured_file(path)
        if not isinstance(raw, dict):
            raise BenchmarkSpecError(f"benchmark seed set must be an object: {path}")
        return BenchmarkSeedSet.model_validate(raw)
    except BenchmarkSpecError:
        raise
    except Exception as exc:  # noqa: BLE001 - normalize loader failures
        raise BenchmarkSpecError(f"failed to load benchmark seed set {path}: {exc}") from exc


def _read_structured_file(path: Path) -> Any:
    suffix = path.suffix.lower()
    text = path.read_text(encoding="utf-8")
    if suffix == ".json":
        return json.loads(text)
    if suffix in {".yaml", ".yml"}:
        try:
            import yaml
        except ImportError as exc:  # pragma: no cover - depends on optional env
            raise BenchmarkSpecError("PyYAML is required to load YAML benchmark specs") from exc
        return yaml.safe_load(text)
    raise BenchmarkSpecError(f"unsupported benchmark spec extension: {path.suffix}")
