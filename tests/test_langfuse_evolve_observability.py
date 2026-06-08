from __future__ import annotations

import asyncio
import sys
import types
from contextlib import contextmanager
from typing import Any


def _install_fake_observability(monkeypatch, *, fail_scores: bool = False) -> dict[str, Any]:
    calls: dict[str, Any] = {
        "contexts": [],
        "scores": [],
        "trace_seeds": [],
    }

    @contextmanager
    def _langfuse_context(**kwargs: Any):
        calls["contexts"].append(kwargs)
        yield object()

    def _create_trace_id(*, seed: str | None = None) -> str:
        calls["trace_seeds"].append(seed)
        return "trace-evolve-test"

    def _score_current_trace(
        name: str,
        value: Any,
        *,
        data_type: str | None = None,
        comment: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if fail_scores:
            raise RuntimeError("Langfuse unavailable")
        calls["scores"].append(
            {
                "name": name,
                "value": value,
                "data_type": data_type,
                "comment": comment,
                "metadata": metadata,
            }
        )

    fake_observability = types.ModuleType("app.services.observability")
    fake_observability.langfuse_context = _langfuse_context
    fake_observability.create_trace_id = _create_trace_id
    fake_observability.score_current_trace = _score_current_trace
    monkeypatch.setitem(sys.modules, "app.services.observability", fake_observability)
    return calls


def test_decide_node_writes_evolve_run_scores(monkeypatch):
    from app.graphs.subgraphs.evolve import nodes

    calls = _install_fake_observability(monkeypatch)
    monkeypatch.setattr(nodes, "_persist_run_state", lambda state: None)

    state = {
        "role": "seer",
        "run_id": "evolve-score-run",
        "parent_hash": "baseline_seer",
        "candidate_hash": "candidate_seer",
        "candidate_skill_dir": "candidate",
        "config": {"auto_promote": False},
        "training_games": [{"game_id": "train-1"}],
        "battle_games": [{"game_id": "battle-1"}, {"game_id": "battle-2"}],
        "proposals": [
            {"proposal_id": "p1", "risk": "low", "quality_score": {"score": 0.81}},
            {"proposal_id": "p2", "risk": "high", "quality_score": {"score": 0.73}},
        ],
        "battle_result": {
            "target_team": "villagers",
            "candidate_win_rate": 0.75,
            "baseline_win_rate": 0.50,
            "win_rate_delta": 0.25,
            "significant": True,
            "candidate": {"error_rate": 0.10, "target_win_rate": 0.75},
            "baseline": {"error_rate": 0.20, "target_win_rate": 0.50},
            "promotion_gate": {
                "promote_allowed": True,
                "recommendation": "promote",
                "decision_quality": {
                    "candidate": {"issue_rate": 0.12},
                    "baseline": {"issue_rate": 0.08},
                },
                "proposal_quality": {
                    "count": 2,
                    "min_score": 0.73,
                    "high_risk": 1,
                },
            },
        },
    }

    out = asyncio.run(nodes.decide_node(state))

    assert out["result"]["recommendation"] == "promote"
    assert calls["trace_seeds"] == ["evolve:evolve-score-run"]
    assert calls["contexts"][0]["trace_name"] == "evolve.run"
    assert calls["contexts"][0]["trace_id"] == "trace-evolve-test"
    assert calls["contexts"][0]["session_id"] == "evolve-score-run"

    by_name = {call["name"]: call for call in calls["scores"]}
    expected_values = {
        "evolve.recommendation": "promote",
        "evolve.status": "reviewing",
        "evolve.candidate_win_rate": 0.75,
        "evolve.baseline_win_rate": 0.50,
        "evolve.win_rate_delta": 0.25,
        "evolve.significant": True,
        "evolve.promote_allowed": True,
        "evolve.candidate_error_rate": 0.10,
        "evolve.baseline_error_rate": 0.20,
        "evolve.candidate_decision_issue_rate": 0.12,
        "evolve.baseline_decision_issue_rate": 0.08,
        "evolve.proposal_count": 2,
        "evolve.proposal_min_quality": 0.73,
        "evolve.proposal_high_risk_count": 1,
    }
    assert {name: by_name[name]["value"] for name in expected_values} == expected_values
    assert by_name["evolve.recommendation"]["data_type"] == "CATEGORICAL"
    assert by_name["evolve.significant"]["data_type"] == "BOOLEAN"
    assert by_name["evolve.candidate_win_rate"]["data_type"] == "NUMERIC"
    assert by_name["evolve.candidate_win_rate"]["metadata"]["run_id"] == "evolve-score-run"
    assert by_name["evolve.candidate_win_rate"]["metadata"]["metric_family"] == "evolve"


def test_evolve_scores_skip_none_values(monkeypatch):
    from app.graphs.subgraphs.evolve import nodes

    calls = _install_fake_observability(monkeypatch)
    monkeypatch.setattr(nodes, "_persist_run_state", lambda state: None)

    state = {
        "role": "seer",
        "run_id": "evolve-none-run",
        "config": {"auto_promote": False},
        "proposals": [],
        "battle_result": {
            "skipped": True,
            "reason": "no_candidate_changes",
            "candidate_win_rate": None,
            "baseline_win_rate": None,
            "significant": None,
            "promotion_gate": {
                "promote_allowed": None,
                "proposal_quality": {"count": 0, "min_score": None, "high_risk": 0},
            },
        },
    }

    asyncio.run(nodes.decide_node(state))

    by_name = {call["name"]: call for call in calls["scores"]}
    assert "evolve.candidate_win_rate" not in by_name
    assert "evolve.baseline_win_rate" not in by_name
    assert "evolve.significant" not in by_name
    assert "evolve.promote_allowed" not in by_name
    assert "evolve.proposal_min_quality" not in by_name
    assert by_name["evolve.recommendation"]["value"] == "reject"
    assert by_name["evolve.proposal_count"]["value"] == 0
    assert by_name["evolve.proposal_high_risk_count"]["value"] == 0


def test_evolve_score_failures_do_not_break_decide_node(monkeypatch):
    from app.graphs.subgraphs.evolve import nodes

    _install_fake_observability(monkeypatch, fail_scores=True)
    monkeypatch.setattr(nodes, "_persist_run_state", lambda state: None)

    state = {
        "role": "seer",
        "run_id": "evolve-fail-open-run",
        "config": {"auto_promote": False},
        "proposals": [{"proposal_id": "p1"}],
        "battle_result": {
            "candidate_win_rate": 0.6,
            "baseline_win_rate": 0.5,
            "significant": True,
            "promotion_gate": {"promote_allowed": True, "recommendation": "promote"},
        },
    }

    out = asyncio.run(nodes.decide_node(state))

    assert out["result"]["recommendation"] == "promote"
    assert out["status"] == "reviewing"
