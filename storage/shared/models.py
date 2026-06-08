"""Shared data models used by both battle and evolution sub-packages.

Re-exports the core data classes from interfaces so downstream code can
import from a single ``models`` namespace.
"""

from __future__ import annotations

from storage.shared.interfaces import (
    DecisionArchiveData,
    DecisionRecordData,
    EvolutionRunData,
    HasToDict,
    RoleHistoryData,
    RoleVersionData,
    SkillProposalData,
    SkillVersionConfigData,
    TimestampProvider,
    compute_hash,
    normalize_skill_path,
    normalize_skill_text,
    storage_timestamp,
)

__all__ = [
    "DecisionArchiveData",
    "DecisionRecordData",
    "EvolutionRunData",
    "HasToDict",
    "RoleHistoryData",
    "RoleVersionData",
    "SkillProposalData",
    "SkillVersionConfigData",
    "TimestampProvider",
    "compute_hash",
    "normalize_skill_path",
    "normalize_skill_text",
    "storage_timestamp",
]
