"""Lightweight, dependency-free data classes and protocols for the storage layer.

Follows the Dependency Inversion Principle: storage defines its own interfaces
so it no longer imports from the agent or engine packages.  Agent code that
wants to persist data adapts its rich objects to these plain-Python data
classes before calling storage.

All fields use plain Python types (str, int, dict, list) — no enums, no
AgentContext, no engine model dependencies.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import PurePosixPath
from typing import Any, Protocol

STORAGE_TZ = timezone(timedelta(hours=8))


# ---------------------------------------------------------------------------
# Protocols
# ---------------------------------------------------------------------------


class HasToDict(Protocol):
    """Anything that can serialize itself to a plain dict."""

    def to_dict(self) -> dict[str, Any]: ...


class TimestampProvider(Protocol):
    """Callable that returns an ISO-8601 timestamp string."""

    def __call__(self) -> str: ...




# ---------------------------------------------------------------------------
# Timestamp helper
# ---------------------------------------------------------------------------


def storage_timestamp() -> str:
    """Beijing-time ISO-8601 timestamp for storage time fields.

    Storage deliberately uses the same +08:00 timestamp semantics as the app
    layer without importing app modules back into storage.
    """
    return datetime.now(STORAGE_TZ).isoformat()


# ---------------------------------------------------------------------------
# Decision data classes
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class DecisionArchiveData:
    """Full trace of a single agent decision — mirrors DecisionArchive.

    All fields are plain Python types with no enum or AgentContext dependency.
    """

    decision_id: str
    index: int
    player_id: int
    role: str
    day: int
    phase: str
    action_type: str
    candidates: list[int]
    observation_summary: dict[str, Any]
    memory_context: dict[str, Any]
    selected_skills: list[str]
    prompt_messages: list[dict[str, Any]]
    raw_output: str
    parsed_decision: dict[str, Any]
    final_response: dict[str, Any]
    source: str
    confidence: float | None
    policy_adjustments: list[str]
    errors: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "index": self.index,
            "player_id": self.player_id,
            "role": self.role,
            "day": self.day,
            "phase": self.phase,
            "action_type": self.action_type,
            "candidates": self.candidates,
            "observation_summary": self.observation_summary,
            "memory_context": self.memory_context,
            "selected_skills": self.selected_skills,
            "prompt_messages": self.prompt_messages,
            "raw_output": self.raw_output,
            "parsed_decision": self.parsed_decision,
            "final_response": self.final_response,
            "source": self.source,
            "confidence": self.confidence,
            "policy_adjustments": self.policy_adjustments,
            "errors": self.errors,
        }


@dataclass(slots=True)
class DecisionRecordData:
    """Record of a single agent decision — mirrors DecisionRecord.

    Uses plain ``str`` for ``action_type`` instead of ``ActionType`` enum.
    """

    decision_id: str
    player_id: int | None = None
    role: str = ""
    day: int = 0
    phase: str = ""
    action_type: str = ""
    selected_target: int | None = None
    selected_choice: str | None = None
    public_text: str = ""
    private_reasoning: str = ""
    confidence: float = 0.0
    alternatives: list[int] = field(default_factory=list)
    rejected_reasons: list[str] = field(default_factory=list)
    selected_skills: list[str] = field(default_factory=list)
    raw_output: str = ""
    source: str = "llm"
    policy_adjustments: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "player_id": self.player_id,
            "role": self.role,
            "day": self.day,
            "phase": self.phase,
            "action_type": self.action_type,
            "selected_target": self.selected_target,
            "selected_choice": self.selected_choice,
            "public_text": self.public_text,
            "private_reasoning": self.private_reasoning,
            "confidence": self.confidence,
            "alternatives": self.alternatives,
            "rejected_reasons": self.rejected_reasons,
            "selected_skills": self.selected_skills,
            "raw_output": self.raw_output,
            "source": self.source,
            "policy_adjustments": self.policy_adjustments,
            "errors": self.errors,
        }


# ---------------------------------------------------------------------------
# Evolution data classes
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class EvolutionRunData:
    """Subset of EvolutionRun fields that storage uses.

    ``baseline_config`` is typed as ``HasToDict | None`` so storage can call
    ``.to_dict()`` without importing SkillVersionConfig.
    """

    run_id: str
    role: str
    parent_hash: str
    status: str
    training_games: int = 0
    battle_games: int = 0
    baseline_config: HasToDict | None = None
    candidate_hash: str | None = None
    battle_result: dict[str, Any] | None = None
    errors: list[str] = field(default_factory=list)
    training_run_id: str | None = None
    training_output_dir: str | None = None
    runtime_state: dict[str, Any] | None = None
    started_at: str | None = None
    finished_at: str | None = None


@dataclass(slots=True)
class SkillProposalData:
    """Proposal for a skill file change — mirrors SkillProposal fields storage uses."""

    proposal_id: str
    target_file: str
    action_type: str
    content: str
    rationale: str
    confidence: float
    risk: str
    expected_metric: str
    expected_direction: str
    evidence: list[HasToDict] = field(default_factory=list)
    status: str = "proposed"


# ---------------------------------------------------------------------------
# Version tracking data classes
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class SkillVersionConfigData:
    """Tracks which role version hash each skill file belongs to."""

    name: str
    created_at: str
    role_versions: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "created_at": self.created_at,
            "role_versions": dict(self.role_versions),
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SkillVersionConfigData:
        return cls(
            name=str(data.get("name", "")),
            created_at=str(data.get("created_at", "")),
            role_versions={str(k): str(v) for k, v in data.get("role_versions", {}).items()},
            notes=[str(n) for n in data.get("notes", [])],
        )


@dataclass(slots=True)
class RoleVersionData:
    """Snapshot of a role's skill set at a point in time."""

    hash: str
    role: str
    skills: dict[str, str]
    created_at: str
    source: str
    parent_hash: str | None = None
    source_run_id: str | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "hash": self.hash,
            "role": self.role,
            "skills": dict(self.skills),
            "created_at": self.created_at,
            "source": self.source,
            "parent_hash": self.parent_hash,
            "source_run_id": self.source_run_id,
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RoleVersionData:
        return cls(
            hash=str(data.get("hash", "")),
            role=str(data.get("role", "")),
            skills={str(k): str(v) for k, v in data.get("skills", {}).items()},
            created_at=str(data.get("created_at", "")),
            source=str(data.get("source", "")),
            parent_hash=data.get("parent_hash"),
            source_run_id=data.get("source_run_id"),
            notes=[str(n) for n in data.get("notes", [])],
        )


@dataclass(slots=True)
class RoleHistoryData:
    """Ordered list of version hashes for a role."""

    role: str
    baseline: str
    versions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "baseline": self.baseline,
            "versions": list(self.versions),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RoleHistoryData:
        return cls(
            role=str(data.get("role", "")),
            baseline=str(data.get("baseline", "")),
            versions=[str(v) for v in data.get("versions", [])],
        )


# ---------------------------------------------------------------------------
# Pure skill-version helper functions.
# These have no app-runtime dependencies — only stdlib (hashlib, pathlib, json).
# ---------------------------------------------------------------------------


def normalize_skill_text(text: str) -> str:
    """Normalize skill file content: CRLF to LF, strip trailing whitespace
    per line, ensure final newline."""
    text = text.replace("\r\n", "\n")
    lines = text.split("\n")
    lines = [line.rstrip() for line in lines]
    result = "\n".join(lines)
    if not result.endswith("\n"):
        result += "\n"
    return result


def normalize_skill_path(path: str) -> str:
    """Normalize a skill file path using PurePosixPath rules.

    Returns the normalized path string.
    Raises ValueError for invalid paths: empty, absolute, containing '..',
    drive paths, or non-.md extension.
    """
    # Normalize backslashes to forward slashes before PurePosixPath
    path = path.replace("\\", "/")
    p = PurePosixPath(path)

    # Reject empty
    if not path or not str(p):
        raise ValueError("Empty path")

    # Reject absolute paths
    if p.is_absolute():
        raise ValueError(f"Absolute path not allowed: {path}")

    # Reject Windows drive letters (e.g., C:\..., D:/...)
    # PurePosixPath.drive is always empty for Windows-style paths, so we
    # must check the raw string explicitly after backslash normalisation.
    if len(path) >= 2 and path[1] == ":" and path[0].isalpha():
        raise ValueError(f"Windows drive path: {path}")

    # Reject drive paths (e.g. C:/...)
    if p.drive:
        raise ValueError(f"Drive path not allowed: {path}")

    # Reject '..' components
    parts = list(p.parts)
    if ".." in parts:
        raise ValueError(f"Path traversal ('..') not allowed: {path}")

    # Reject non-.md extension
    if p.suffix != ".md":
        raise ValueError(f"Only .md files allowed, got: {path}")

    # Normalize: collapse redundant separators via PurePosixPath
    normalized = str(p)
    return normalized


def compute_hash(skills: dict[str, str]) -> str:
    """Compute a content hash for a set of skills.

    Normalizes paths and content, detects duplicate normalized paths,
    then produces a sha256 hash of the manifest.
    Returns first 12 hex characters.
    """
    normalized: dict[str, str] = {}
    for raw_path, content in skills.items():
        np = normalize_skill_path(raw_path)
        if np in normalized:
            raise ValueError(f"Duplicate normalized path: {np} (from {raw_path})")
        normalized[np] = normalize_skill_text(content)

    # Build deterministic manifest
    manifest = {
        "hash_schema": 1,
        "skills": {k: normalized[k] for k in sorted(normalized)},
    }
    payload = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    full_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return full_hash[:12]
