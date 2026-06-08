from __future__ import annotations

import asyncio
import sys
import types
from typing import Any


def _install_fake_observability(monkeypatch, *, raise_on_score: bool = False) -> list[dict[str, Any]]:
    captured: list[dict[str, Any]] = []

    def _score_current_trace(
        name: str,
        value: Any,
        *,
        data_type: str | None = None,
        comment: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if raise_on_score:
            raise RuntimeError("langfuse down")
        captured.append({
            "name": name,
            "value": value,
            "data_type": data_type,
            "comment": comment,
            "metadata": metadata,
        })

    fake_observability = types.ModuleType("app.services.observability")
    fake_observability.score_current_trace = _score_current_trace
    monkeypatch.setitem(sys.modules, "app.services.observability", fake_observability)
    return captured


def _review_state(*, game_id: str = "g_review_langfuse") -> dict[str, Any]:
    return {
        "game_id": game_id,
        "config": {"enable_llm_judge": True, "judge_max_decisions": 1},
        "roles": {"1": "seer", "2": "werewolf"},
        "winner": "villagers",
        "decisions": [
            {
                "decision_id": "d_check",
                "player_id": 1,
                "role": "seer",
                "day": 1,
                "phase": "night",
                "action_type": "seer_check",
                "selected_target": 2,
                "private_reasoning": "2 looks suspicious",
                "confidence": 0.9,
            }
        ],
        "game_events": [
            {"event_type": "night_end", "day": 1, "phase": "night"},
        ],
    }


def test_review_decision_judge_writes_langfuse_game_scores(monkeypatch):
    from app.graphs.shared.nodes.review import review_node

    captured = _install_fake_observability(monkeypatch)

    async def fake_judge(_messages):
        return (
            '{"schema_version":"1.0","decision_id":"d_check","score":8.5,'
            '"quality":"good","reason":"查验狼人有信息增量",'
            '"evidence_refs":["rule_natural_key_action"],"mistake_tags":[],'
            '"suggestion":"继续围绕查验链组织发言","confidence":0.8}'
        )

    state = _review_state()
    state["decision_judge_fn"] = fake_judge

    result = asyncio.run(review_node(state))

    assert result["review"]["status"] == "ok"
    assert result["review"]["decision_judge"]["status"] == "ok"

    by_name = {call["name"]: call for call in captured}
    assert by_name["review.decision_judge_average_score"]["value"] == 8.5
    assert by_name["review.decision_judge_judged"]["value"] == 1
    assert by_name["review.decision_judge_failed"]["value"] == 0
    assert by_name["review.decision_judge_status"]["value"] == "ok"
    assert by_name["review.decision_judge_bad_count"]["value"] == 0
    assert by_name["review.decision_judge_good_count"]["value"] == 1
    assert by_name["review.decision_judge_average_score"]["data_type"] == "NUMERIC"
    assert by_name["review.decision_judge_status"]["data_type"] == "CATEGORICAL"
    assert by_name["review.decision_judge_average_score"]["metadata"]["metric_family"] == "review.decision_judge"
    assert by_name["review.decision_judge_average_score"]["metadata"]["game_id"] == "g_review_langfuse"


def test_review_decision_judge_score_skips_none_and_missing_fields(monkeypatch):
    from app.graphs.shared.nodes import review as review_nodes

    captured = _install_fake_observability(monkeypatch)

    review_nodes._score_langfuse_decision_judge_report(
        {
            "status": "skipped",
            "summary": {"average_score": None, "quality_counts": {"good": None, "bad": 2}},
            "metrics": {"judged": 0, "failed": None},
        },
        game_id="g_missing_fields",
    )

    by_name = {call["name"]: call for call in captured}
    assert "review.decision_judge_average_score" not in by_name
    assert "review.decision_judge_failed" not in by_name
    assert "review.decision_judge_good_count" not in by_name
    assert by_name["review.decision_judge_status"]["value"] == "skipped"
    assert by_name["review.decision_judge_judged"]["value"] == 0
    assert by_name["review.decision_judge_bad_count"]["value"] == 2


def test_review_decision_judge_langfuse_errors_do_not_affect_review(monkeypatch):
    from app.graphs.shared.nodes.review import review_node

    _install_fake_observability(monkeypatch, raise_on_score=True)

    async def fake_judge(_messages):
        return (
            '{"schema_version":"1.0","decision_id":"d_check","score":4.0,'
            '"quality":"bad","reason":"missed critical clue",'
            '"evidence_refs":["rule_natural_key_action"],"mistake_tags":["bad_target"],'
            '"suggestion":"re-check target priority","confidence":0.8}'
        )

    state = _review_state(game_id="g_langfuse_down")
    state["decision_judge_fn"] = fake_judge

    result = asyncio.run(review_node(state))

    assert result["review"]["status"] == "ok"
    assert result["review"]["decision_judge"]["status"] == "ok"
    assert result["review"]["decision_judge"]["summary"]["average_score"] == 4.0
    assert not any("Langfuse" in warning for warning in result.get("warnings", []))
