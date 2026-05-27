"""Tests for skill proposal evolvable check."""
import tempfile
from pathlib import Path
from agent.cognition.skill_evolution import apply_skill_proposals, SkillProposal


def _write_skill(tmpdir: str, name: str, body: str, evolvable: bool = True) -> Path:
    """Write a skill file with given evolvable flag."""
    skill_dir = Path(tmpdir) / "test_role"
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_file = skill_dir / f"{name}.md"
    content = f"---\nname: {name}\nrole: test_role\nevolvable: {str(evolvable).lower()}\n---\n\n{body}"
    skill_file.write_text(content, encoding="utf-8")
    return skill_file


def _make_proposal(skill: str = "test_skill") -> SkillProposal:
    return SkillProposal(
        proposal_id="test_001",
        role="test_role",
        skill=skill,
        operation="append_rule",
        proposal="Always do X in situation Y",
        risk="low",
        evidence_cards=["card_1", "card_2", "card_3"],
        confidence=0.9,
    )


def test_evolvable_skill_gets_patched():
    with tempfile.TemporaryDirectory() as td:
        _write_skill(td, "test_skill", "original body", evolvable=True)
        records = apply_skill_proposals(
            [_make_proposal()],
            target_skill_root=td,
            min_confidence=0.75,
            min_evidence_cards=3,
        )
        assert len(records) == 1


def test_non_evolvable_skill_skipped():
    with tempfile.TemporaryDirectory() as td:
        _write_skill(td, "test_skill", "original body", evolvable=False)
        records = apply_skill_proposals(
            [_make_proposal()],
            target_skill_root=td,
            min_confidence=0.75,
            min_evidence_cards=3,
        )
        assert len(records) == 0


def test_missing_evolvable_defaults_false():
    """Skills without evolvable in front-matter should NOT be patched."""
    with tempfile.TemporaryDirectory() as td:
        skill_dir = Path(td) / "test_role"
        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_file = skill_dir / "test_skill.md"
        skill_file.write_text("---\nname: test_skill\nrole: test_role\n---\n\nbody", encoding="utf-8")
        records = apply_skill_proposals(
            [_make_proposal()],
            target_skill_root=td,
            min_confidence=0.75,
            min_evidence_cards=3,
        )
        assert len(records) == 0
