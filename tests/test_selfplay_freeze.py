"""Tests for skill_dir freeze enforcement."""
from pathlib import Path

import pytest

from agent.evaluation.selfplay import SelfPlayConfig


def test_selfplay_config_skill_dir_default_none():
    c = SelfPlayConfig(games=5)
    assert c.skill_dir is None


def test_selfplay_config_skill_dir_set():
    c = SelfPlayConfig(games=5, skill_dir=Path("/tmp/skills"))
    assert c.skill_dir == Path("/tmp/skills")
