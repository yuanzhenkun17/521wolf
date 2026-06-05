"""Tests for agent.evolution.pattern_engine — Bayesian pattern discovery."""
from __future__ import annotations

import uuid

from agent.learning.pattern_engine import Pattern, PatternEngine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pattern(**overrides) -> Pattern:
    defaults = dict(
        pattern_id=str(uuid.uuid4()),
        role="seer",
        situation="seer:seer_check:night:early",
        recommendation="seer_check:target=2",
        win_rate_with=0.6,
        win_rate_without=0.5,
        sample_size=10,
        confidence=0.3,
        status="candidate",
        source_games=["g1", "g2"],
        alpha=3.0,
        beta=2.0,
        created_at="2026-01-01T00:00:00+08:00",
        updated_at="2026-01-01T00:00:00+08:00",
    )
    defaults.update(overrides)
    return Pattern(**defaults)


# ---------------------------------------------------------------------------
# Pattern.to_dict() / from_dict() round-trip
# ---------------------------------------------------------------------------


def test_pattern_to_dict_round_trip():
    p = _make_pattern()
    d = p.to_dict()

    assert d["pattern_id"] == p.pattern_id
    assert d["role"] == "seer"
    assert d["situation"] == "seer:seer_check:night:early"
    assert d["recommendation"] == "seer_check:target=2"
    assert d["win_rate_with"] == 0.6
    assert d["win_rate_without"] == 0.5
    assert d["sample_size"] == 10
    assert d["confidence"] == 0.3
    assert d["status"] == "candidate"
    assert d["source_games"] == ["g1", "g2"]
    assert d["alpha"] == 3.0
    assert d["beta"] == 2.0

    expected_keys = {
        "pattern_id", "role", "situation", "recommendation",
        "win_rate_with", "win_rate_without", "sample_size", "confidence",
        "status", "source_games", "alpha", "beta", "created_at", "updated_at",
    }
    assert set(d.keys()) == expected_keys


def test_pattern_from_dict_round_trip():
    original = _make_pattern()
    d = original.to_dict()
    restored = Pattern.from_dict(d)

    assert restored.pattern_id == original.pattern_id
    assert restored.role == original.role
    assert restored.situation == original.situation
    assert restored.recommendation == original.recommendation
    assert restored.win_rate_with == original.win_rate_with
    assert restored.win_rate_without == original.win_rate_without
    assert restored.sample_size == original.sample_size
    assert restored.confidence == original.confidence
    assert restored.status == original.status
    assert restored.source_games == original.source_games
    assert restored.alpha == original.alpha
    assert restored.beta == original.beta


def test_pattern_from_dict_with_missing_fields():
    """from_dict uses defaults for missing keys."""
    restored = Pattern.from_dict({})
    assert restored.pattern_id == ""
    assert restored.role == ""
    assert restored.status == "candidate"
    assert restored.alpha == 1.0
    assert restored.beta == 1.0
    assert restored.source_games == []


# ---------------------------------------------------------------------------
# bayesian_update
# ---------------------------------------------------------------------------


def test_bayesian_update_win_increments_alpha():
    engine = PatternEngine()
    p = _make_pattern(alpha=2.0, beta=3.0, sample_size=5)

    engine.bayesian_update(p, won=True)

    assert p.alpha == 3.0
    assert p.beta == 3.0
    assert p.sample_size == 6
    assert p.win_rate_with == 3.0 / 6.0


def test_bayesian_update_loss_increments_beta():
    engine = PatternEngine()
    p = _make_pattern(alpha=2.0, beta=3.0, sample_size=5)

    engine.bayesian_update(p, won=False)

    assert p.alpha == 2.0
    assert p.beta == 4.0
    assert p.sample_size == 6
    assert p.win_rate_with == 2.0 / 6.0


def test_bayesian_update_multiple_rounds():
    engine = PatternEngine()
    p = _make_pattern(alpha=1.0, beta=1.0, sample_size=0)

    # 3 wins, 1 loss
    for _ in range(3):
        engine.bayesian_update(p, won=True)
    engine.bayesian_update(p, won=False)

    assert p.alpha == 4.0
    assert p.beta == 2.0
    assert p.sample_size == 4
    assert abs(p.win_rate_with - 4.0 / 6.0) < 1e-9


# ---------------------------------------------------------------------------
# _compute_confidence
# ---------------------------------------------------------------------------


def test_compute_confidence_symmetric_is_zero():
    engine = PatternEngine()
    # alpha == beta -> mean == 0.5 -> deviation == 0 -> confidence == 0
    assert engine._compute_confidence(5.0, 5.0) == 0.0


def test_compute_confidence_strong_bias_high():
    engine = PatternEngine()
    # alpha=20, beta=2 -> mean=0.909 -> deviation=0.409
    # concentration = 22/23 ~ 0.957
    # confidence = 0.409 * 2 * 0.957 ~ 0.782
    conf = engine._compute_confidence(20.0, 2.0)
    assert 0.7 < conf < 0.9


def test_compute_confidence_zero_total():
    engine = PatternEngine()
    assert engine._compute_confidence(0.0, 0.0) == 0.0


def test_compute_confidence_capped_at_one():
    engine = PatternEngine()
    # Extreme values: alpha=1000, beta=1
    conf = engine._compute_confidence(1000.0, 1.0)
    assert conf <= 1.0


def test_compute_confidence_mild_bias():
    engine = PatternEngine()
    # alpha=3, beta=2 -> mean=0.6, deviation=0.1
    # concentration = 5/6 ~ 0.833
    # confidence ~ 0.1 * 2 * 0.833 ~ 0.167
    conf = engine._compute_confidence(3.0, 2.0)
    assert 0.1 < conf < 0.2


# ---------------------------------------------------------------------------
# _check_lifecycle_transition
# ---------------------------------------------------------------------------


def test_lifecycle_candidate_to_active():
    engine = PatternEngine()
    p = _make_pattern(
        status="candidate",
        sample_size=9,
        alpha=10.0,
        beta=2.0,
    )
    # Before: not enough samples
    engine._check_lifecycle_transition(p)
    assert p.status == "candidate"

    # Push sample_size to threshold and ensure confidence is high enough
    p.sample_size = 10
    p.confidence = engine._compute_confidence(p.alpha, p.beta)
    engine._check_lifecycle_transition(p)
    assert p.status == "active"


def test_lifecycle_active_to_crystallized():
    engine = PatternEngine()
    p = _make_pattern(
        status="active",
        sample_size=29,
        alpha=28.0,
        beta=2.0,
    )
    # Not enough samples yet
    engine._check_lifecycle_transition(p)
    assert p.status == "active"

    # Push to crystallization threshold
    p.sample_size = 30
    p.confidence = engine._compute_confidence(p.alpha, p.beta)
    engine._check_lifecycle_transition(p)
    assert p.status == "crystallized"


def test_lifecycle_no_transition_for_archived():
    engine = PatternEngine()
    p = _make_pattern(status="archived", sample_size=100, confidence=0.9)
    engine._check_lifecycle_transition(p)
    assert p.status == "archived"


def test_lifecycle_candidate_not_active_if_low_confidence():
    engine = PatternEngine()
    p = _make_pattern(
        status="candidate",
        sample_size=10,
        alpha=5.0,
        beta=5.0,  # symmetric -> confidence=0
    )
    p.confidence = engine._compute_confidence(p.alpha, p.beta)
    engine._check_lifecycle_transition(p)
    assert p.status == "candidate"  # confidence too low


# ---------------------------------------------------------------------------
# update_after_game — creates new and updates existing
# ---------------------------------------------------------------------------


def test_update_after_game_creates_new_pattern():
    engine = PatternEngine()
    decisions = [
        {
            "role": "seer",
            "action_type": "seer_check",
            "phase": "night",
            "day": 1,
            "selected_target": 2,
        },
    ]
    player_roles = {1: "seer", 2: "werewolf"}

    updated = engine.update_after_game("g1", decisions, "villagers", player_roles)

    assert len(updated) == 1
    assert updated[0].role == "seer"
    assert updated[0].status == "candidate"
    assert updated[0].sample_size == 1
    assert "g1" in updated[0].source_games
    assert len(engine) == 1


def test_update_after_game_updates_existing_pattern():
    engine = PatternEngine()
    decision = {
        "role": "seer",
        "action_type": "seer_check",
        "phase": "night",
        "day": 1,
        "selected_target": 2,
    }
    player_roles = {1: "seer", 2: "werewolf"}

    # First game creates pattern
    engine.update_after_game("g1", [decision], "villagers", player_roles)
    assert len(engine) == 1

    # Second game with same signature updates it
    engine.update_after_game("g2", [decision], "villagers", player_roles)
    assert len(engine) == 1

    p = engine.get_all_patterns()[0]
    assert p.sample_size == 2
    assert "g1" in p.source_games
    assert "g2" in p.source_games


def test_update_after_game_loss_sets_low_win_rate():
    engine = PatternEngine()
    decision = {
        "role": "werewolf",
        "action_type": "werewolf_kill",
        "phase": "night",
        "day": 1,
        "selected_target": 1,
    }
    player_roles = {1: "seer", 2: "werewolf"}

    # Werewolf loses
    engine.update_after_game("g1", [decision], "villagers", player_roles)
    p = engine.get_all_patterns()[0]
    # Loss: alpha=1, beta=2 -> win_rate = 1/3
    assert abs(p.win_rate_with - 1.0 / 3.0) < 1e-9


# ---------------------------------------------------------------------------
# get_relevant_patterns
# ---------------------------------------------------------------------------


def test_get_relevant_patterns_returns_matching():
    engine = PatternEngine()

    # Create two active patterns for seer
    p1 = _make_pattern(
        role="seer",
        situation="seer:seer_check:night:early",
        status="active",
        confidence=0.5,
        sample_size=15,
    )
    p2 = _make_pattern(
        role="seer",
        situation="seer:seer_check:night:mid",
        status="active",
        confidence=0.8,
        sample_size=20,
    )
    # One pattern for werewolf (should not match)
    p3 = _make_pattern(
        role="werewolf",
        situation="werewolf:werewolf_kill:night:early",
        status="active",
        confidence=0.9,
        sample_size=25,
    )
    engine._patterns[p1.pattern_id] = p1
    engine._patterns[p2.pattern_id] = p2
    engine._patterns[p3.pattern_id] = p3

    results = engine.get_relevant_patterns("seer", "night", 1)
    assert len(results) == 2
    # Sorted by confidence descending
    assert results[0].confidence >= results[1].confidence


def test_get_relevant_patterns_excludes_candidate():
    engine = PatternEngine()
    p = _make_pattern(status="candidate", confidence=0.9)
    engine._patterns[p.pattern_id] = p

    results = engine.get_relevant_patterns("seer", "night", 1)
    assert len(results) == 0


def test_get_relevant_patterns_filters_by_action_type():
    engine = PatternEngine()
    p1 = _make_pattern(
        situation="seer:seer_check:night:early",
        status="active",
    )
    p2 = _make_pattern(
        situation="seer:speak:day:early",
        status="active",
    )
    engine._patterns[p1.pattern_id] = p1
    engine._patterns[p2.pattern_id] = p2

    results = engine.get_relevant_patterns("seer", "night", 1, action_type="seer_check")
    assert len(results) == 1
    assert "seer_check" in results[0].situation


def test_get_relevant_patterns_max_five():
    engine = PatternEngine()
    for i in range(10):
        p = _make_pattern(
            situation=f"seer:action_{i}:night:early",
            status="active",
            confidence=0.1 * i,
        )
        engine._patterns[p.pattern_id] = p

    results = engine.get_relevant_patterns("seer", "night", 1)
    assert len(results) == 5


# ---------------------------------------------------------------------------
# run_lifecycle_gc
# ---------------------------------------------------------------------------


def test_lifecycle_gc_archives_low_confidence():
    engine = PatternEngine()
    p = _make_pattern(
        status="active",
        sample_size=60,
        alpha=30.0,
        beta=30.0,  # symmetric -> confidence = 0
    )
    p.confidence = engine._compute_confidence(p.alpha, p.beta)
    engine._patterns[p.pattern_id] = p

    result = engine.run_lifecycle_gc()

    assert p.pattern_id in result["archived"]
    assert p.status == "archived"


def test_lifecycle_gc_keeps_high_confidence():
    engine = PatternEngine()
    p = _make_pattern(
        status="active",
        sample_size=60,
        alpha=55.0,
        beta=5.0,  # high confidence
    )
    p.confidence = engine._compute_confidence(p.alpha, p.beta)
    engine._patterns[p.pattern_id] = p

    result = engine.run_lifecycle_gc()

    assert p.pattern_id not in result["archived"]
    assert p.status == "active"


def test_lifecycle_gc_skips_already_archived():
    engine = PatternEngine()
    p = _make_pattern(status="archived", sample_size=100, confidence=0.0)
    engine._patterns[p.pattern_id] = p

    result = engine.run_lifecycle_gc()

    assert result["archived"] == []
    assert result["deprecated"] == []


def test_lifecycle_gc_deprecates_stale_patterns():
    engine = PatternEngine()
    p = _make_pattern(
        status="active",
        sample_size=1,
        source_games=["g1"],
    )
    engine._patterns[p.pattern_id] = p
    engine._game_count = 300  # way more than 200, pattern very stale

    result = engine.run_lifecycle_gc()

    assert p.pattern_id in result["deprecated"]
    assert p.status == "deprecated"


# ---------------------------------------------------------------------------
# Engine serialisation
# ---------------------------------------------------------------------------


def test_engine_to_dict_from_dict_round_trip():
    engine = PatternEngine()
    decisions = [
        {"role": "witch", "action_type": "witch_act", "phase": "night", "day": 2},
    ]
    engine.update_after_game("g1", decisions, "villagers", {1: "witch"})

    d = engine.to_dict()
    restored = PatternEngine.from_dict(d)

    assert restored._game_count == engine._game_count
    assert len(restored) == len(engine)
