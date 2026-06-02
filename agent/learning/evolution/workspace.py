"""Temporary skill workspaces for versioned evolution runs."""

from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path

from agent.learning.evolution.models import SkillVersionConfig
from agent.learning.evolution.store import VersionStore

_log = logging.getLogger(__name__)


def build_composite_skill_dir(store: VersionStore, config: SkillVersionConfig) -> Path:
    """Assemble a temporary role skill directory from a version config."""
    tmpdir = Path(tempfile.mkdtemp(prefix="evo_skills_"))
    for role, hash_value in config.role_versions.items():
        try:
            src = store.get_skill_dir(role, hash_value)
        except FileNotFoundError:
            _log.warning("Missing skill dir for %s/%s, skipping", role, hash_value)
            continue
        shutil.copytree(src, tmpdir / role)
    return tmpdir
