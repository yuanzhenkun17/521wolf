"""Tests for skill metadata extension (evolution)."""
from agent.skill_system.loader import MarkdownSkill, parse_front_matter, _load_skill_file
from pathlib import Path
import tempfile


def test_evolution_default_disabled():
    skill = MarkdownSkill(name="test")
    assert skill.evolution["enabled"] is False
    assert skill.evolution["allowed_actions"] == []


def test_parse_evolution_enabled():
    text = """---
name: x
evolution:
  enabled: true
  allowed_actions:
    - append_rule
    - rewrite_section
---
body"""
    front, _ = parse_front_matter(text)
    assert front["evolution"]["enabled"] is True
    assert "append_rule" in front["evolution"]["allowed_actions"]


def test_load_skill_with_evolution():
    with tempfile.TemporaryDirectory() as td:
        md = Path(td) / "test.md"
        content = """---
name: my_skill
role: werewolf
evolution:
  enabled: true
  allowed_actions:
    - append_rule
---
body text"""
        md.write_text(content)
        skill = _load_skill_file(md)
        assert skill is not None
        assert skill.evolution["enabled"] is True
        assert "append_rule" in skill.evolution["allowed_actions"]
