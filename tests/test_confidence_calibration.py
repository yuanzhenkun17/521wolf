from agent.evaluation.confidence_calibration import (
    calibrate_decisions,
    calibrate_decisions_by_group,
    decision_correctness,
    merge_calibration_reports,
)
from agent.observability.decision_log import DecisionRecord
from engine.models import ActionType, Role


def _record(player_id, action_type, target=None, choice=None, confidence=0.5):
    return DecisionRecord(
        action_type=action_type,
        player_id=player_id,
        selected_target=target,
        selected_choice=choice,
        confidence=confidence,
    )


def test_vote_correctness_uses_actor_alignment():
    roles = {1: Role.VILLAGER, 2: Role.WEREWOLF, 3: Role.VILLAGER}

    assert decision_correctness(_record(1, ActionType.EXILE_VOTE, target=2), roles) is True
    assert decision_correctness(_record(1, ActionType.EXILE_VOTE, target=3), roles) is False
    assert decision_correctness(_record(2, ActionType.EXILE_VOTE, target=3), roles) is True
    assert decision_correctness(_record(2, ActionType.EXILE_VOTE, target=2), roles) is False


def test_skill_correctness_is_objective():
    roles = {
        1: Role.WITCH,
        2: Role.WEREWOLF,
        3: Role.VILLAGER,
        4: Role.HUNTER,
        5: Role.GUARD,
    }

    assert decision_correctness(_record(1, ActionType.WITCH_ACT, target=2, choice="poison"), roles) is True
    assert decision_correctness(_record(1, ActionType.WITCH_ACT, target=3, choice="poison"), roles) is False
    assert decision_correctness(_record(4, ActionType.HUNTER_SHOOT, target=2), roles) is True
    assert decision_correctness(_record(5, ActionType.GUARD_PROTECT, target=3), roles) is None


def test_calibrate_decisions_computes_bucketed_ece():
    roles = {1: Role.VILLAGER, 2: Role.WEREWOLF, 3: Role.VILLAGER}
    report = calibrate_decisions(
        [
            _record(1, ActionType.EXILE_VOTE, target=2, confidence=0.8),
            _record(1, ActionType.EXILE_VOTE, target=3, confidence=0.9),
        ],
        roles,
    )

    assert report["confidence_calibration_count"] == 2
    assert report["confidence_buckets"]["0.8-1.0"]["count"] == 2
    assert report["confidence_buckets"]["0.8-1.0"]["correct"] == 1
    assert abs(report["confidence_buckets"]["0.8-1.0"]["avg_confidence"] - 0.85) < 0.001
    assert abs(report["confidence_calibration_error"] - 0.35) < 0.001


def test_calibrate_decisions_by_group():
    roles = {1: Role.VILLAGER, 2: Role.WEREWOLF, 3: Role.VILLAGER}
    report = calibrate_decisions_by_group(
        [
            _record(1, ActionType.EXILE_VOTE, target=2, confidence=0.8),
            _record(2, ActionType.EXILE_VOTE, target=3, confidence=0.6),
        ],
        roles,
        lambda player_id: "v1" if player_id == 1 else "v2",
    )

    assert report["v1"]["confidence_calibration_count"] == 1
    assert report["v2"]["confidence_calibration_count"] == 1
    assert report["v1"]["confidence_buckets"]["0.8-1.0"]["accuracy"] == 1.0
    assert report["v2"]["confidence_buckets"]["0.6-0.8"]["accuracy"] == 1.0


def test_merge_calibration_reports_keeps_weighted_error():
    merged = merge_calibration_reports([
        {
            "confidence_buckets": {
                "0.8-1.0": {"count": 1, "correct": 1, "confidence_sum": 0.8},
            },
        },
        {
            "confidence_buckets": {
                "0.8-1.0": {"count": 1, "correct": 0, "confidence_sum": 0.9},
            },
        },
    ])

    assert merged["confidence_calibration_count"] == 2
    assert merged["confidence_buckets"]["0.8-1.0"]["correct"] == 1
    assert abs(merged["confidence_calibration_error"] - 0.35) < 0.001
