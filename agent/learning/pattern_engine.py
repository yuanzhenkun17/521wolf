"""Pattern Library with Bayesian updates.

Discovers and maintains statistical patterns from game outcomes.
Patterns represent situation-action correlations with win rate evidence.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

from agent.common import beijing_now_iso

logger = logging.getLogger(__name__)


@dataclass
class Pattern:
    """A statistical pattern discovered from game outcomes."""

    pattern_id: str
    role: str
    situation: str  # structured condition description
    recommendation: str  # recommended action
    win_rate_with: float  # win rate when following this recommendation
    win_rate_without: float  # win rate when not following it
    sample_size: int
    confidence: float  # 0-1
    status: str  # candidate/active/crystallized/archived/deprecated
    source_games: list[str]
    alpha: float  # Beta distribution alpha (wins + 1)
    beta: float  # Beta distribution beta (losses + 1)
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "pattern_id": self.pattern_id,
            "role": self.role,
            "situation": self.situation,
            "recommendation": self.recommendation,
            "win_rate_with": self.win_rate_with,
            "win_rate_without": self.win_rate_without,
            "sample_size": self.sample_size,
            "confidence": self.confidence,
            "status": self.status,
            "source_games": list(self.source_games),
            "alpha": self.alpha,
            "beta": self.beta,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Pattern:
        return cls(
            pattern_id=str(data.get("pattern_id", "")),
            role=str(data.get("role", "")),
            situation=str(data.get("situation", "")),
            recommendation=str(data.get("recommendation", "")),
            win_rate_with=float(data.get("win_rate_with", 0.5)),
            win_rate_without=float(data.get("win_rate_without", 0.5)),
            sample_size=int(data.get("sample_size", 0)),
            confidence=float(data.get("confidence", 0.0)),
            status=str(data.get("status", "candidate")),
            source_games=[str(g) for g in data.get("source_games", [])],
            alpha=float(data.get("alpha", 1.0)),
            beta=float(data.get("beta", 1.0)),
            created_at=str(data.get("created_at", "")),
            updated_at=str(data.get("updated_at", "")),
        )


class PatternEngine:
    """Incremental pattern discovery and Bayesian updating."""

    # Lifecycle thresholds
    ACTIVE_MIN_SAMPLES = 10
    ACTIVE_MIN_CONFIDENCE = 0.3
    CRYSTALIZED_MIN_SAMPLES = 30
    CRYSTALIZED_MIN_CONFIDENCE = 0.7
    ARCHIVE_MAX_SAMPLES = 50
    ARCHIVE_LOW_CONFIDENCE = 0.2

    def __init__(self) -> None:
        self._patterns: dict[str, Pattern] = {}
        self._game_count = 0

    def update_after_game(
        self,
        game_id: str,
        decisions: list[dict[str, Any]],
        winner: str,
        player_roles: dict[int, str],
    ) -> list[Pattern]:
        """
        Process a completed game's decisions and update patterns.

        For each key decision:
        1. Build a situation signature (role, action_type, phase, day_range)
        2. Look up matching existing patterns
        3. If match: Bayesian update win_rate and confidence
        4. If no match: create new candidate pattern

        Returns list of updated/created patterns.
        """
        self._game_count += 1
        updated_patterns: list[Pattern] = []

        for decision in decisions:
            try:
                signature = self._build_situation_signature(decision)
                role = decision.get("role", "unknown")
                won = self._determine_win(decision, winner, player_roles)

                # Look for existing pattern with matching signature
                matching_pattern = self._find_matching_pattern(signature, role)

                if matching_pattern:
                    # Bayesian update existing pattern
                    self.bayesian_update(matching_pattern, won)
                    if game_id not in matching_pattern.source_games:
                        matching_pattern.source_games.append(game_id)
                        # Keep only last 100 game IDs to avoid unbounded growth
                        if len(matching_pattern.source_games) > 100:
                            matching_pattern.source_games = matching_pattern.source_games[-100:]
                    matching_pattern.updated_at = beijing_now_iso()
                    updated_patterns.append(matching_pattern)
                else:
                    # Create new candidate pattern
                    now = beijing_now_iso()
                    alpha = 2.0 if won else 1.0
                    beta = 1.0 if won else 2.0
                    new_pattern = Pattern(
                        pattern_id=str(uuid.uuid4()),
                        role=role,
                        situation=signature,
                        recommendation=self._extract_recommendation(decision),
                        win_rate_with=alpha / (alpha + beta),
                        win_rate_without=0.5,  # baseline
                        sample_size=1,
                        confidence=self._compute_confidence(alpha, beta),
                        status="candidate",
                        source_games=[game_id],
                        alpha=alpha,
                        beta=beta,
                        created_at=now,
                        updated_at=now,
                    )
                    self._patterns[new_pattern.pattern_id] = new_pattern
                    updated_patterns.append(new_pattern)

            except Exception as e:
                logger.warning(f"Failed to process decision in game {game_id}: {e}")
                continue

        return updated_patterns

    def _build_situation_signature(
        self,
        decision: dict[str, Any],
    ) -> str:
        """
        Build a normalized situation signature from a decision.
        Format: "{role}:{action_type}:{phase}:{day_bucket}"

        day_bucket: 'early' (day 1-3), 'mid' (day 4-7), 'late' (day 8+)
        """
        role = str(decision.get("role", "unknown"))
        action_type = str(decision.get("action_type", "unknown"))
        phase = str(decision.get("phase", "unknown"))
        day = int(decision.get("day", 1))

        if day <= 3:
            day_bucket = "early"
        elif day <= 7:
            day_bucket = "mid"
        else:
            day_bucket = "late"

        return f"{role}:{action_type}:{phase}:{day_bucket}"

    def bayesian_update(self, pattern: Pattern, won: bool) -> None:
        """
        Beta-Binomial Bayesian update.

        Prior: Beta(alpha, beta)
        Observation: won (Bernoulli trial)
        Posterior: alpha += 1 if won, beta += 1 if lost

        Then update:
        - win_rate_with = alpha / (alpha + beta)
        - confidence = computed from posterior
        - sample_size += 1

        Then check lifecycle transitions:
        - candidate -> active (if sample >= 10 and confidence >= 0.3)
        - active -> crystallized (if sample >= 30 and confidence >= 0.7)
        """
        if won:
            pattern.alpha += 1.0
        else:
            pattern.beta += 1.0

        pattern.sample_size += 1
        pattern.win_rate_with = pattern.alpha / (pattern.alpha + pattern.beta)
        pattern.confidence = self._compute_confidence(pattern.alpha, pattern.beta)

        self._check_lifecycle_transition(pattern)

    def _compute_confidence(self, alpha: float, beta: float) -> float:
        """
        Compute confidence from Beta distribution parameters.
        Uses a simplified measure based on how far the mean is from 0.5
        and how concentrated the distribution is.

        confidence = |mean - 0.5| * 2 * concentration
        where concentration = (alpha + beta) / (alpha + beta + 1)
        capped at 1.0
        """
        total = alpha + beta
        if total <= 0:
            return 0.0

        mean = alpha / total
        concentration = total / (total + 1.0)
        deviation = abs(mean - 0.5)

        confidence = deviation * 2.0 * concentration
        return min(1.0, max(0.0, confidence))

    def _check_lifecycle_transition(self, pattern: Pattern) -> None:
        """Check and apply lifecycle status transitions."""
        if pattern.status == "archived" or pattern.status == "deprecated":
            return

        if pattern.status == "candidate":
            if (
                pattern.sample_size >= self.ACTIVE_MIN_SAMPLES
                and pattern.confidence >= self.ACTIVE_MIN_CONFIDENCE
            ):
                pattern.status = "active"
                logger.info(
                    f"Pattern {pattern.pattern_id} promoted to active "
                    f"(samples={pattern.sample_size}, confidence={pattern.confidence:.3f})"
                )

        elif pattern.status == "active":
            if (
                pattern.sample_size >= self.CRYSTALIZED_MIN_SAMPLES
                and pattern.confidence >= self.CRYSTALIZED_MIN_CONFIDENCE
            ):
                pattern.status = "crystallized"
                logger.info(
                    f"Pattern {pattern.pattern_id} crystallized "
                    f"(samples={pattern.sample_size}, confidence={pattern.confidence:.3f})"
                )

    def get_relevant_patterns(
        self,
        role: str,
        phase: str,
        day: int,
        action_type: str | None = None,
    ) -> list[Pattern]:
        """
        Query patterns matching a current situation for runtime injection.

        Returns patterns where:
        - role matches
        - status is 'active' or 'crystallized'
        - situation signature partially matches (role + action_type at minimum)

        Sorted by confidence descending, max 5 results.
        """
        if day <= 3:
            day_bucket = "early"
        elif day <= 7:
            day_bucket = "mid"
        else:
            day_bucket = "late"

        matching: list[Pattern] = []

        for pattern in self._patterns.values():
            if pattern.role != role:
                continue
            if pattern.status not in ("active", "crystallized"):
                continue

            # Parse signature: role:action_type:phase:day_bucket
            sig_parts = pattern.situation.split(":")
            if len(sig_parts) < 2:
                continue

            pattern_role = sig_parts[0]
            pattern_action = sig_parts[1]
            pattern_phase = sig_parts[2] if len(sig_parts) > 2 else ""
            pattern_day_bucket = sig_parts[3] if len(sig_parts) > 3 else ""

            # Role must match (already checked above, but be explicit)
            if pattern_role != role:
                continue

            # If action_type specified, it must match
            if action_type and pattern_action != action_type:
                continue

            # Phase matching is optional but preferred
            # Day bucket matching is optional but preferred
            matching.append(pattern)

        # Sort by confidence descending, then by sample_size descending
        matching.sort(key=lambda p: (p.confidence, p.sample_size), reverse=True)

        return matching[:5]

    def run_lifecycle_gc(self) -> dict[str, list[str]]:
        """
        Run garbage collection on pattern lifecycle.

        - Archive: confidence < 0.2 after 50+ samples
        - Deprecate: not updated in last 200 games (track via game count)

        Returns dict with 'archived' and 'deprecated' pattern IDs.
        """
        archived: list[str] = []
        deprecated: list[str] = []

        for pattern_id, pattern in self._patterns.items():
            if pattern.status in ("archived", "deprecated"):
                continue

            # Archive low-confidence patterns with sufficient samples
            if (
                pattern.sample_size >= self.ARCHIVE_MAX_SAMPLES
                and pattern.confidence < self.ARCHIVE_LOW_CONFIDENCE
            ):
                pattern.status = "archived"
                archived.append(pattern_id)
                logger.info(
                    f"Pattern {pattern_id} archived "
                    f"(samples={pattern.sample_size}, confidence={pattern.confidence:.3f})"
                )
                continue

            # Deprecate patterns not seen in recent games
            if len(pattern.source_games) > 0:
                # Check if pattern was updated recently (within last 200 games)
                # We track this by checking if any recent game IDs are in source_games
                # Since we don't track global game IDs, use a heuristic:
                # if sample_size is very low compared to total games, it's stale
                if self._game_count > 200 and pattern.sample_size < self._game_count * 0.01:
                    pattern.status = "deprecated"
                    deprecated.append(pattern_id)
                    logger.info(
                        f"Pattern {pattern_id} deprecated (stale: "
                        f"samples={pattern.sample_size}, total_games={self._game_count})"
                    )

        return {"archived": archived, "deprecated": deprecated}

    def _find_matching_pattern(self, signature: str, role: str) -> Pattern | None:
        """Find an existing pattern with matching signature and role."""
        for pattern in self._patterns.values():
            if pattern.role == role and pattern.situation == signature:
                return pattern
        return None

    def _determine_win(
        self,
        decision: dict[str, Any],
        winner: str,
        player_roles: dict[int, str],
    ) -> bool:
        """
        Determine if the decision's role won the game.

        Args:
            decision: Decision dict with 'role' or 'seat' field
            winner: Winner string ('werewolves' or 'villagers')
            player_roles: Map of seat/player_id -> role

        Returns:
            True if the decision's role is on the winning team
        """
        role = decision.get("role", "")
        if not role:
            # Try to get role from seat
            seat = decision.get("seat")
            if seat is not None and seat in player_roles:
                role = player_roles[seat]

        if not role:
            return False

        # Determine team from role
        werewolf_roles = {"werewolf", "white_wolf_king", "wolf"}
        is_werewolf = any(wr in role.lower() for wr in werewolf_roles)

        winner_normalized = winner.lower()
        werewolf_won = (
            "werewolf" in winner_normalized
            or winner_normalized == "werewolves"
        )

        return is_werewolf == werewolf_won

    def _extract_recommendation(self, decision: dict[str, Any]) -> str:
        """Extract a recommendation string from a decision."""
        action_type = decision.get("action_type", "unknown")
        selected_target = decision.get("selected_target")
        selected_choice = decision.get("selected_choice")

        if selected_target is not None:
            return f"{action_type}:target={selected_target}"
        elif selected_choice:
            return f"{action_type}:choice={selected_choice}"
        else:
            return action_type

    def get_pattern(self, pattern_id: str) -> Pattern | None:
        """Get a pattern by ID."""
        return self._patterns.get(pattern_id)

    def get_all_patterns(self) -> list[Pattern]:
        """Get all patterns."""
        return list(self._patterns.values())

    def to_dict(self) -> dict[str, Any]:
        """Serialize the entire engine state to a dict."""
        return {
            "game_count": self._game_count,
            "patterns": {
                pid: pattern.to_dict()
                for pid, pattern in self._patterns.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PatternEngine:
        """Deserialize engine state from a dict."""
        engine = cls()
        engine._game_count = int(data.get("game_count", 0))
        patterns_data = data.get("patterns", {})
        for pid, pdata in patterns_data.items():
            engine._patterns[pid] = Pattern.from_dict(pdata)
        return engine

    def __len__(self) -> int:
        return len(self._patterns)

    def __repr__(self) -> str:
        status_counts: dict[str, int] = {}
        for pattern in self._patterns.values():
            status_counts[pattern.status] = status_counts.get(pattern.status, 0) + 1
        status_str = ", ".join(f"{k}={v}" for k, v in sorted(status_counts.items()))
        return f"PatternEngine(games={self._game_count}, patterns=[{status_str}])"
