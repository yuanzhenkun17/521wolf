"""Shared storage utilities -- compatibility re-exports from canonical interfaces."""

from __future__ import annotations

from storage.interfaces import (
    HasToDict,
    TimestampProvider,
    compute_hash,
    normalize_skill_path,
    normalize_skill_text,
    storage_timestamp,
    DecisionArchiveData,
    DecisionRecordData,
    EvolutionRunData,
    RoleHistoryData,
    RoleVersionData,
    SkillProposalData,
    SkillVersionConfigData,
)

__all__ = [
    "HasToDict",
    "TimestampProvider",
    "compute_hash",
    "normalize_skill_path",
    "normalize_skill_text",
    "storage_timestamp",
    "DecisionArchiveData",
    "DecisionRecordData",
    "EvolutionRunData",
    "RoleHistoryData",
    "RoleVersionData",
    "SkillProposalData",
    "SkillVersionConfigData",
]
