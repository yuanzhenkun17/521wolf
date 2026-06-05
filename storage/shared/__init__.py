"""Shared storage utilities -- re-export from interfaces for convenience."""

from __future__ import annotations

from storage.shared.interfaces import (
    HasToDict,
    TimestampProvider,
    compute_hash,
    normalize_skill_path,
    normalize_skill_text,
    storage_timestamp,
    DecisionArchiveData,
    DecisionRecordData,
    EvolutionRunData,
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
    "SkillProposalData",
    "SkillVersionConfigData",
]
