"""Tests for skill metadata extension (evolvable, category)."""
from agent.skill_system.loader import MarkdownSkill, parse_front_matter, _load_skill_file
from pathlib import Path
import tempfile


def test_evolvable_default_false():
    skill = MarkdownSkill(name="test")
    assert skill.evolvable is False


def test_category_default_strategy():
    skill = MarkdownSkill(name="test")
    assert skill.category == "strategy"


def test_parse_evolvable_true():
    text = """---
name: x
evolvable: true
---
body"""
    front, _ = parse_front_matter(text)
    assert front["evolvable"] is True


def test_parse_category_foundation():
    text = """---
name: x
category: foundation
---
body"""
    front, _ = parse_front_matter(text)
    assert front["category"] == "foundation"


def test_load_skill_with_metadata():
    with tempfile.TemporaryDirectory() as td:
        md = Path(td) / "test.md"
        content = """---
name: my_skill
category: foundation
evolvable: true
role: werewolf
---
body text"""
        md.write_text(content)
        skill = _load_skill_file(md)
        assert skill is not None
        assert skill.category == "foundation"
        assert skill.evolvable is True
