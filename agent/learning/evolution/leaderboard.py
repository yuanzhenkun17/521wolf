"""Role evolution leaderboard.

Aggregates per-role metrics from battle summaries into RoleLeaderboardEntry
objects, computes Wilson confidence intervals, and produces advisory
recommendations (promote / caution / reject).
"""

from __future__ import annotations

import logging
from agent.learning.evolution.models import RoleLeaderboardEntry
from agent.learning.stats import wilson_ci95 as wilson_ci

_log = logging.getLogger(__name__)


# Side mapping
_WEREWOLF_ROLES = {"werewolf", "white_wolf_king"}


def target_side_for_role(role: str) -> str:
    """Return the faction side for a role: 'werewolves' or 'villagers'."""
    return "werewolves" if role in _WEREWOLF_ROLES else "villagers"


# Metric keys
_ROLE_METRIC_KEYS = [
    "role_weighted_score",
    "speech_score",
    "vote_score",
    "skill_score",
    "information_score",
    "cooperation_score",
    "fallback_rate",
    "bad_case_rate",
]

_ROLE_METRIC_FIELDS = [f"target_role_{k}" for k in _ROLE_METRIC_KEYS]

_SIDE_WIN_RATE_FIELD = "target_side_win_rate"


def _safe_metric(metrics: dict, role: str, key: str) -> float:
    """Extract a float metric, returning 0.0 if missing."""
    role_metrics = metrics.get(role, {})
    return float(role_metrics.get(key, 0.0))


def _side_win_rate(metrics: dict, role: str) -> float:
    """Extract the win rate for the target role's side."""
    side = target_side_for_role(role)
    side_metrics = metrics.get(side, {})
    return float(side_metrics.get("win_rate", 0.0))


def _side_win_count(metrics: dict, role: str, games_played: int) -> int:
    """Extract the number of wins for the target role's side."""
    side = target_side_for_role(role)
    side_metrics = metrics.get(side, {})
    wr = float(side_metrics.get("win_rate", 0.0))
    return round(wr * games_played)


def _build_entry(
    *,
    hash: str,
    role: str,
    is_baseline: bool,
    total_games: int,
    wins: int,
    losses: int,
    role_metric_sums: dict[str, float],
    side_win_rate_sum: float,
    side_win_count: int,
    n_summaries: int,
) -> RoleLeaderboardEntry:
    """Construct a RoleLeaderboardEntry from accumulated aggregates."""
    n = n_summaries if n_summaries > 0 else 1

    entry = RoleLeaderboardEntry(
        hash=hash,
        role=role,
        is_baseline=is_baseline,
        total_games=total_games,
        battle_record=f"W:{wins} L:{losses}",
        data_sufficient=total_games >= 10,
        recommendation="",  # filled later by compute_recommendation
    )

    # Average role metrics across summaries
    for key in _ROLE_METRIC_KEYS:
        field = f"target_role_{key}"
        setattr(entry, field, role_metric_sums.get(key, 0.0) / n)

    # Average side win rate + Wilson CI
    avg_wr = side_win_rate_sum / n if n > 0 else 0.0
    entry.target_side_win_rate = avg_wr
    entry.target_side_win_rate_ci = wilson_ci(side_win_count, total_games)

    return entry


# Aggregation
def aggregate_role_leaderboard(
    role: str,
    battle_summaries: list[dict],
) -> list[RoleLeaderboardEntry]:
    """Aggregate battle summaries into RoleLeaderboardEntry list.

    Each battle summary is expected to contain:
      - baseline_config: {role_versions: {role: hash}}
      - candidate_config: {role_versions: {role: hash}}
      - baseline_metrics: {role: {win_rate, scores, ...}}
      - candidate_metrics: {role: {win_rate, scores, ...}}
      - games_played: int
      - seeds: list[int]

    For each unique hash seen in battle summaries, creates a
    RoleLeaderboardEntry with metrics filtered to only the target role's
    players.
    """
    # Per-hash accumulators
    # key = hash, value = dict of running state
    accum: dict[str, dict] = {}

    for summary in battle_summaries:
        games_played = int(summary.get("games_played", 0))
        baseline_config = summary.get("baseline_config", {})
        candidate_config = summary.get("candidate_config", {})
        baseline_metrics = summary.get("baseline_metrics", {})
        candidate_metrics = summary.get("candidate_metrics", {})

        baseline_hash = baseline_config.get("role_versions", {}).get(role)
        candidate_hash = candidate_config.get("role_versions", {}).get(role)

        if not baseline_hash or not candidate_hash:
            _log.debug("Skipping summary without target role hashes")
            continue

        # Determine which side won by comparing side win rates
        base_side_wr = _side_win_rate(baseline_metrics, role)
        cand_side_wr = _side_win_rate(candidate_metrics, role)

        # Winner: whichever config's side has higher win rate
        # If candidate side wins -> candidate hash gets a win, baseline gets a loss
        # If baseline side wins -> baseline hash gets a win, candidate gets a loss
        if cand_side_wr > base_side_wr:
            cand_win, base_win = games_played, 0
        elif base_side_wr > cand_side_wr:
            cand_win, base_win = 0, games_played
        else:
            # Tie — split evenly (should be rare)
            cand_win = games_played // 2
            base_win = games_played - cand_win

        # Initialize accumulators if needed
        for h in (baseline_hash, candidate_hash):
            if h not in accum:
                accum[h] = {
                    "total_games": 0,
                    "wins": 0,
                    "losses": 0,
                    "role_metric_sums": {k: 0.0 for k in _ROLE_METRIC_KEYS},
                    "side_win_rate_sum": 0.0,
                    "side_win_count": 0,
                    "n_summaries": 0,
                    "is_baseline": False,  # will be set below
                }

        # Mark baseline hash
        accum[baseline_hash]["is_baseline"] = True

        # Baseline hash metrics
        a = accum[baseline_hash]
        a["total_games"] += games_played
        a["wins"] += base_win
        a["losses"] += cand_win
        a["n_summaries"] += 1
        for key in _ROLE_METRIC_KEYS:
            a["role_metric_sums"][key] += _safe_metric(baseline_metrics, role, key)
        base_wr = _side_win_rate(baseline_metrics, role)
        a["side_win_rate_sum"] += base_wr
        a["side_win_count"] += _side_win_count(baseline_metrics, role, games_played)

        # Candidate hash metrics
        a = accum[candidate_hash]
        a["total_games"] += games_played
        a["wins"] += cand_win
        a["losses"] += base_win
        a["n_summaries"] += 1
        for key in _ROLE_METRIC_KEYS:
            a["role_metric_sums"][key] += _safe_metric(candidate_metrics, role, key)
        cand_wr = _side_win_rate(candidate_metrics, role)
        a["side_win_rate_sum"] += cand_wr
        a["side_win_count"] += _side_win_count(candidate_metrics, role, games_played)

    if not accum:
        _log.warning("No battle summaries contained role '%s'", role)
        return []

    # Build entries
    entries: list[RoleLeaderboardEntry] = []
    baseline_entry: RoleLeaderboardEntry | None = None

    for hash_val, state in accum.items():
        entry = _build_entry(
            hash=hash_val,
            role=role,
            is_baseline=state["is_baseline"],
            total_games=state["total_games"],
            wins=state["wins"],
            losses=state["losses"],
            role_metric_sums=state["role_metric_sums"],
            side_win_rate_sum=state["side_win_rate_sum"],
            side_win_count=state["side_win_count"],
            n_summaries=state["n_summaries"],
        )
        entries.append(entry)
        if state["is_baseline"]:
            baseline_entry = entry

    # Compute deltas and recommendations
    if baseline_entry is not None:
        for entry in entries:
            if entry.hash == baseline_entry.hash:
                entry.delta_vs_baseline = {}
                entry.recommendation = "promote"  # baseline is always "promote"
                continue
            entry.delta_vs_baseline = _compute_deltas(entry, baseline_entry)
            entry.recommendation = compute_recommendation(entry, baseline_entry)
    else:
        # No baseline identified — mark all as caution
        _log.warning("No baseline entry found for role '%s'", role)
        for entry in entries:
            entry.recommendation = "caution"

    # Sort: baseline first, then by total_games descending
    entries.sort(key=lambda e: (not e.is_baseline, -e.total_games))

    return entries


def _compute_deltas(
    entry: RoleLeaderboardEntry, baseline: RoleLeaderboardEntry
) -> dict[str, float]:
    """Compute per-metric deltas (entry - baseline)."""
    deltas: dict[str, float] = {}
    for field in _ROLE_METRIC_FIELDS:
        deltas[field] = round(getattr(entry, field) - getattr(baseline, field), 4)
    deltas[_SIDE_WIN_RATE_FIELD] = round(
        entry.target_side_win_rate - baseline.target_side_win_rate, 4
    )
    return deltas


# Recommendation
def compute_recommendation(
    entry: RoleLeaderboardEntry, baseline_entry: RoleLeaderboardEntry
) -> str:
    """Compute advisory recommendation: 'promote' | 'caution' | 'reject'.

    Rules (evaluated in order, first match wins):
    - battle_games < 10: 'caution' (data insufficient)
    - target_role_role_weighted_score < baseline: 'reject'
    - target_role_fallback_rate > baseline: 'reject'
    - target_side_win_rate drops > 10% from baseline: 'reject'
    - any core metric slightly below baseline: 'caution'
    - all metrics at or above baseline: 'promote'
    """
    # Insufficient data
    if entry.total_games < 10:
        return "caution"

    # Hard rejects
    if entry.target_role_role_weighted_score < baseline_entry.target_role_role_weighted_score:
        return "reject"

    if entry.target_role_fallback_rate > baseline_entry.target_role_fallback_rate:
        return "reject"

    win_rate_drop = baseline_entry.target_side_win_rate - entry.target_side_win_rate
    if win_rate_drop > 0.10:
        return "reject"

    # Check for slight regressions in any core metric
    for field in _ROLE_METRIC_FIELDS:
        if field == "target_role_fallback_rate":
            # Already checked above for hard reject; here check slight increase
            if getattr(entry, field) > getattr(baseline_entry, field):
                return "caution"
        elif field == "target_role_bad_case_rate":
            if getattr(entry, field) > getattr(baseline_entry, field):
                return "caution"
        else:
            # For score metrics, lower is bad
            if getattr(entry, field) < getattr(baseline_entry, field):
                return "caution"

    return "promote"
