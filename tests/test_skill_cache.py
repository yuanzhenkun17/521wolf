"""Tests for per-root skill cache and applicable_actions behavior."""
from pathlib import Path
import pytest
from agent.skill_system.router import _get_skill_index, _SKILL_CACHE, SkillIndex
from agent.skill_system.loader import MarkdownSkill
from engine.models import ActionType, Role


@pytest.fixture(autouse=True)
def _clean_skill_cache():
    """Ensure skill cache is clean before and after each test."""
    _SKILL_CACHE.clear()
    yield
    _SKILL_CACHE.clear()


def test_skill_index_cached_per_root(tmp_path):
    idx1 = _get_skill_index(tmp_path)
    idx2 = _get_skill_index(tmp_path)
    assert idx1 is idx2


def test_different_roots_different_indexes(tmp_path):
    d1 = tmp_path / "v1"
    d2 = tmp_path / "v2"
    d1.mkdir()
    d2.mkdir()
    idx1 = _get_skill_index(d1)
    idx2 = _get_skill_index(d2)
    assert idx1 is not idx2


def test_empty_applicable_actions_always_matches():
    skill = MarkdownSkill(
        name="persona", role=Role.WEREWOLF,
        applicable_actions=set(),
    )
    assert not skill.applicable_actions or ActionType.SPEAK in skill.applicable_actions
    assert not skill.applicable_actions or ActionType.EXILE_VOTE in skill.applicable_actions


def test_non_empty_applicable_actions_filters():
    skill = MarkdownSkill(
        name="fake_seer", role=Role.WEREWOLF,
        applicable_actions={ActionType.SPEAK, ActionType.SHERIFF_SPEAK},
    )
    assert ActionType.SPEAK in skill.applicable_actions
    assert ActionType.EXILE_VOTE not in skill.applicable_actions
