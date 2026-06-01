"""Shared metric aggregation helpers for selfplay and role evolution."""

from __future__ import annotations


def _new_role_accum() -> dict[str, float | int]:
    """Create a fresh per-role accumulator dict."""
    return {
        "players": 0,
        "wins": 0,
        "losses": 0,
        "total_score_sum": 0.0,
        "role_weighted_score_sum": 0.0,
        "speech_score_sum": 0.0,
        "vote_score_sum": 0.0,
        "skill_score_sum": 0.0,
        "information_score_sum": 0.0,
        "cooperation_score_sum": 0.0,
        "decision_count": 0,
        "fallback_count": 0,
        "policy_adjusted_count": 0,
        "bad_case_count": 0,
    }


def finalize_role_metrics(state: dict[str, float | int]) -> dict[str, float | int]:
    """Convert raw accumulator state into finalised per-role metrics."""
    players = int(state.get("players", 0))
    decisions = int(state.get("decision_count", 0))
    bad_cases = int(state.get("bad_case_count", 0))

    def _avg(field: str) -> float:
        if players <= 0:
            return 0.0
        return round(float(state.get(f"{field}_sum", 0.0)) / players, 3)

    return {
        "players": players,
        "wins": int(state.get("wins", 0)),
        "losses": int(state.get("losses", 0)),
        "win_rate": round(int(state.get("wins", 0)) / players, 3) if players else 0.0,
        "total_score": _avg("total_score"),
        "role_weighted_score": _avg("role_weighted_score"),
        "speech_score": _avg("speech_score"),
        "vote_score": _avg("vote_score"),
        "skill_score": _avg("skill_score"),
        "information_score": _avg("information_score"),
        "cooperation_score": _avg("cooperation_score"),
        "decision_count": decisions,
        "fallback_count": int(state.get("fallback_count", 0)),
        "policy_adjusted_count": int(state.get("policy_adjusted_count", 0)),
        "fallback_rate": round(int(state.get("fallback_count", 0)) / decisions, 4)
        if decisions else 0.0,
        "policy_adjusted_rate": round(int(state.get("policy_adjusted_count", 0)) / decisions, 4)
        if decisions else 0.0,
        "bad_case_count": bad_cases,
        "bad_case_rate": round(bad_cases / decisions, 4) if decisions else 0.0,
    }
