"""Tests for agent.evolution.models — knowledge versioning data classes."""
from __future__ import annotations

from agent.learning.evolution.models import (
    BattleMetrics,
    KnowledgeDiff,
    KnowledgePackage,
    ProvenanceRecord,
    SkillFileRef,
)


# ---------------------------------------------------------------------------
# SkillFileRef round-trip
# ---------------------------------------------------------------------------


def test_skill_file_ref_to_dict():
    ref = SkillFileRef(path="seer/strategy.md", content_hash="abc123def456")
    d = ref.to_dict()
    assert d == {"path": "seer/strategy.md", "content_hash": "abc123def456"}


def test_skill_file_ref_from_dict():
    d = {"path": "witch/tips.md", "content_hash": "hash789"}
    ref = SkillFileRef.from_dict(d)
    assert ref.path == "witch/tips.md"
    assert ref.content_hash == "hash789"


def test_skill_file_ref_round_trip():
    original = SkillFileRef(path="werewolf/kill_order.md", content_hash="aabbcc")
    restored = SkillFileRef.from_dict(original.to_dict())
    assert restored.path == original.path
    assert restored.content_hash == original.content_hash


# ---------------------------------------------------------------------------
# ProvenanceRecord round-trip
# ---------------------------------------------------------------------------


def test_provenance_record_to_dict():
    prov = ProvenanceRecord(
        source="evolution",
        run_id="run-42",
        proposal_ids=["p1", "p2"],
        evidence_game_ids=["g10", "g11"],
        rejected_pattern_ids=["rp1"],
    )
    d = prov.to_dict()

    assert d["source"] == "evolution"
    assert d["run_id"] == "run-42"
    assert d["proposal_ids"] == ["p1", "p2"]
    assert d["evidence_game_ids"] == ["g10", "g11"]
    assert d["rejected_pattern_ids"] == ["rp1"]


def test_provenance_record_from_dict():
    d = {
        "source": "seed",
        "run_id": None,
        "proposal_ids": [],
        "evidence_game_ids": [],
        "rejected_pattern_ids": [],
    }
    prov = ProvenanceRecord.from_dict(d)
    assert prov.source == "seed"
    assert prov.run_id is None
    assert prov.proposal_ids == []


def test_provenance_record_from_dict_defaults():
    """from_dict handles missing keys gracefully."""
    prov = ProvenanceRecord.from_dict({})
    assert prov.source == "unknown"
    assert prov.run_id is None
    assert prov.proposal_ids == []
    assert prov.evidence_game_ids == []
    assert prov.rejected_pattern_ids == []


def test_provenance_record_round_trip():
    original = ProvenanceRecord(
        source="manual",
        run_id="r1",
        proposal_ids=["p1"],
        evidence_game_ids=["g1"],
        rejected_pattern_ids=["rp1", "rp2"],
    )
    restored = ProvenanceRecord.from_dict(original.to_dict())
    assert restored.source == original.source
    assert restored.run_id == original.run_id
    assert restored.proposal_ids == original.proposal_ids
    assert restored.evidence_game_ids == original.evidence_game_ids
    assert restored.rejected_pattern_ids == original.rejected_pattern_ids


# ---------------------------------------------------------------------------
# BattleMetrics round-trip
# ---------------------------------------------------------------------------


def test_battle_metrics_to_dict():
    metrics = BattleMetrics(
        win_rate=0.65,
        score=0.72,
        speech_score=0.6,
        vote_score=0.7,
        skill_score=0.8,
        games_played=20,
        confidence_interval=(0.55, 0.75),
    )
    d = metrics.to_dict()

    assert d["win_rate"] == 0.65
    assert d["score"] == 0.72
    assert d["speech_score"] == 0.6
    assert d["vote_score"] == 0.7
    assert d["skill_score"] == 0.8
    assert d["games_played"] == 20
    assert d["confidence_interval"] == [0.55, 0.75]


def test_battle_metrics_to_dict_none_ci():
    metrics = BattleMetrics()
    d = metrics.to_dict()
    assert d["confidence_interval"] is None
    assert d["win_rate"] == 0.0
    assert d["games_played"] == 0


def test_battle_metrics_from_dict():
    d = {
        "win_rate": 0.55,
        "score": 0.60,
        "speech_score": 0.5,
        "vote_score": 0.6,
        "skill_score": 0.7,
        "games_played": 10,
        "confidence_interval": [0.45, 0.65],
    }
    metrics = BattleMetrics.from_dict(d)
    assert metrics.win_rate == 0.55
    assert metrics.games_played == 10
    assert metrics.confidence_interval == (0.45, 0.65)


def test_battle_metrics_from_dict_defaults():
    metrics = BattleMetrics.from_dict({})
    assert metrics.win_rate == 0.0
    assert metrics.score == 0.0
    assert metrics.games_played == 0
    assert metrics.confidence_interval is None


def test_battle_metrics_round_trip():
    original = BattleMetrics(
        win_rate=0.7,
        score=0.8,
        speech_score=0.75,
        vote_score=0.85,
        skill_score=0.9,
        games_played=50,
        confidence_interval=(0.6, 0.8),
    )
    restored = BattleMetrics.from_dict(original.to_dict())
    assert restored.win_rate == original.win_rate
    assert restored.score == original.score
    assert restored.games_played == original.games_played
    assert restored.confidence_interval == original.confidence_interval


# ---------------------------------------------------------------------------
# KnowledgePackage round-trip
# ---------------------------------------------------------------------------


def _make_knowledge_package(**overrides) -> KnowledgePackage:
    defaults = dict(
        version_id="v1",
        role="seer",
        parent_id=None,
        skills=[SkillFileRef("seer/strategy.md", "hash1")],
        patterns=[{"pattern_id": "p1", "role": "seer", "confidence": 0.5}],
        provenance=ProvenanceRecord(source="seed"),
        metrics=BattleMetrics(win_rate=0.6, games_played=10),
        created_at="2026-01-01T00:00:00+08:00",
    )
    defaults.update(overrides)
    return KnowledgePackage(**defaults)


def test_knowledge_package_to_dict():
    pkg = _make_knowledge_package()
    d = pkg.to_dict()

    assert d["version_id"] == "v1"
    assert d["role"] == "seer"
    assert d["parent_id"] is None
    assert len(d["skills"]) == 1
    assert d["skills"][0] == {"path": "seer/strategy.md", "content_hash": "hash1"}
    assert len(d["patterns"]) == 1
    assert d["provenance"]["source"] == "seed"
    assert d["metrics"]["win_rate"] == 0.6
    assert d["created_at"] == "2026-01-01T00:00:00+08:00"


def test_knowledge_package_from_dict():
    d = {
        "version_id": "v2",
        "role": "witch",
        "parent_id": "v1",
        "skills": [{"path": "witch/potion.md", "content_hash": "h2"}],
        "patterns": [],
        "provenance": {"source": "evolution", "proposal_ids": ["p1"]},
        "metrics": {"win_rate": 0.7, "games_played": 20},
        "created_at": "2026-02-01T00:00:00+08:00",
    }
    pkg = KnowledgePackage.from_dict(d)

    assert pkg.version_id == "v2"
    assert pkg.role == "witch"
    assert pkg.parent_id == "v1"
    assert len(pkg.skills) == 1
    assert pkg.skills[0].path == "witch/potion.md"
    assert pkg.provenance.source == "evolution"
    assert pkg.metrics.win_rate == 0.7


def test_knowledge_package_round_trip():
    original = _make_knowledge_package()
    restored = KnowledgePackage.from_dict(original.to_dict())

    assert restored.version_id == original.version_id
    assert restored.role == original.role
    assert restored.parent_id == original.parent_id
    assert len(restored.skills) == len(original.skills)
    assert restored.skills[0].path == original.skills[0].path
    assert restored.provenance.source == original.provenance.source
    assert restored.metrics.win_rate == original.metrics.win_rate


def test_knowledge_package_no_metrics():
    pkg = _make_knowledge_package(metrics=None)
    d = pkg.to_dict()
    assert d["metrics"] is None

    restored = KnowledgePackage.from_dict(d)
    assert restored.metrics is None


def test_knowledge_package_empty_skills_and_patterns():
    pkg = _make_knowledge_package(skills=[], patterns=[])
    d = pkg.to_dict()
    assert d["skills"] == []
    assert d["patterns"] == []

    restored = KnowledgePackage.from_dict(d)
    assert restored.skills == []
    assert restored.patterns == []


# ---------------------------------------------------------------------------
# KnowledgeDiff.to_dict()
# ---------------------------------------------------------------------------


def test_knowledge_diff_to_dict():
    diff = KnowledgeDiff(
        skill_changes=[
            {
                "file": "seer/strategy.md",
                "action": "modified",
                "before_lines": ["old line"],
                "after_lines": ["new line"],
            },
        ],
        patterns_added=[{"pattern_id": "p_new"}],
        patterns_removed=[{"pattern_id": "p_old"}],
        patterns_updated=[{"pattern_id": "p_upd"}],
        metrics_delta={"win_rate": 0.05, "games_played": 5.0},
    )
    d = diff.to_dict()

    assert len(d["skill_changes"]) == 1
    assert d["skill_changes"][0]["action"] == "modified"
    assert len(d["patterns_added"]) == 1
    assert len(d["patterns_removed"]) == 1
    assert len(d["patterns_updated"]) == 1
    assert d["metrics_delta"]["win_rate"] == 0.05


def test_knowledge_diff_to_dict_no_metrics_delta():
    diff = KnowledgeDiff(
        skill_changes=[],
        patterns_added=[],
        patterns_removed=[],
        patterns_updated=[],
        metrics_delta=None,
    )
    d = diff.to_dict()
    assert d["metrics_delta"] is None
    assert d["skill_changes"] == []
