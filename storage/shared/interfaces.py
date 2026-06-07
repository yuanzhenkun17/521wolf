"""Compatibility re-exports for storage shared interfaces.

The canonical implementation lives in ``storage.interfaces``. Keep this module
so older ``storage.shared.interfaces`` imports do not fork the data contracts.
"""

from __future__ import annotations

from storage.interfaces import (
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
