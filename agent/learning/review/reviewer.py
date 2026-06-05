"""Post-game decision review with counterfactual analysis.

Identifies turning-point decisions, labels their quality, and generates
what-if counterfactual scenarios.  All logic is rule-based (no LLM).
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from agent.common import beijing_now_iso
from agent.common.action_types import (
    NIGHT_SKILL_ACTION_TYPES,
    SPEECH_ACTION_TYPES,
    VOTE_ACTION_TYPES,
)

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Role / team helpers (duplicated from evaluator to keep modules independent)
# ---------------------------------------------------------------------------

_WEREWOLF_ROLES = frozenset({"werewolf", "white_wolf_king"})
_GOD_ROLES = frozenset({"seer", "witch", "hunter", "guard"})


def _is_werewolf(role: str) -> bool:
    return role.lower() in _WEREWOLF_ROLES


def _is_god(role: str) -> bool:
    return role.lower() in _GOD_ROLES


def _is_good(role: str) -> bool:
    return not _is_werewolf(role)


def _team_won(role: str, winner: str) -> bool:
    wolves_win = "werewolf" in winner.lower()
    return _is_werewolf(role) == wolves_win


def _get_seat(decision: dict) -> int:
    for key in ("player_id", "seat", "player_seat"):
        v = decision.get(key)
        if v is not None:
            return int(v)
    return -1


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class DecisionReview:
    """Review of a single turning-point decision."""

    id: str
    game_id: str
    decision_id: str
    player_seat: int
    day: int
    phase: str
    action_type: str
    quality: str  # 'good', 'bad', 'questionable'
    reason: str
    alternative_action: str | None
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "game_id": self.game_id,
            "decision_id": self.decision_id,
            "player_seat": self.player_seat,
            "day": self.day,
            "phase": self.phase,
            "action_type": self.action_type,
            "quality": self.quality,
            "reason": self.reason,
            "alternative_action": self.alternative_action,
            "created_at": self.created_at,
        }


@dataclass
class Counterfactual:
    """What-if analysis for a turning-point decision."""

    id: str
    game_id: str
    decision_id: str
    what_if: str
    likely_outcome: str
    confidence: float
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "game_id": self.game_id,
            "decision_id": self.decision_id,
            "what_if": self.what_if,
            "likely_outcome": self.likely_outcome,
            "confidence": round(self.confidence, 3),
            "created_at": self.created_at,
        }


# ---------------------------------------------------------------------------
# Reviewer
# ---------------------------------------------------------------------------


class GameReviewer:
    """Identifies turning points and generates counterfactuals."""

    def review_game(
        self,
        game_id: str,
        *,
        events: list[dict[str, Any]],
        decisions: list[dict[str, Any]],
        evaluation: Any,  # GameEvaluation (from evaluator)
        player_roles: dict[int, str],
        winner: str,
    ) -> tuple[list[DecisionReview], list[Counterfactual]]:
        """Review all decisions, identify turning points, and generate counterfactuals.

        Returns
        -------
        reviews:
            One ``DecisionReview`` per turning-point decision.
        counterfactuals:
            One ``Counterfactual`` per turning-point decision where a what-if
            scenario could be generated.
        """
        reviews: list[DecisionReview] = []
        counterfactuals: list[Counterfactual] = []

        # Index evaluations by seat for quick lookup
        eval_by_seat: dict[int, Any] = {}
        if evaluation is not None and hasattr(evaluation, "players"):
            for pe in evaluation.players:
                eval_by_seat[pe.player_seat] = pe

        for decision in decisions:
            seat = _get_seat(decision)
            role = player_roles.get(seat, "unknown")

            if not self._is_turning_point(decision, events, player_roles):
                continue

            decision_id = str(
                decision.get("decision_id")
                or f"game{game_id}_p{seat}_d{decision.get('day', 0)}_{decision.get('action_type', '')}"
            )

            quality, reason, alternative = self._judge_decision(
                decision, events, player_roles, winner, eval_by_seat.get(seat),
            )

            now = beijing_now_iso()
            review = DecisionReview(
                id=str(uuid.uuid4()),
                game_id=game_id,
                decision_id=decision_id,
                player_seat=seat,
                day=int(decision.get("day", 0)),
                phase=str(decision.get("phase", "")),
                action_type=str(decision.get("action_type", "")),
                quality=quality,
                reason=reason,
                alternative_action=alternative,
                created_at=now,
            )
            reviews.append(review)

            cf = self._generate_counterfactual(decision, player_roles, winner, game_id, decision_id)
            if cf is not None:
                counterfactuals.append(cf)

        return reviews, counterfactuals

    # ------------------------------------------------------------------
    # Turning-point detection
    # ------------------------------------------------------------------

    def _is_turning_point(
        self,
        decision: dict,
        events: list[dict],
        player_roles: dict[int, str],
    ) -> bool:
        """A decision is a turning point if it had high impact on game state.

        Criteria:
        - Night kill that targeted a god
        - Witch save or poison decision
        - Exile vote that removed a key player (god or wolf)
        - Seer check that found a wolf
        - Hunter shot
        - White wolf king explosion
        """
        action = decision.get("action_type", "")
        seat = _get_seat(decision)
        target = decision.get("selected_target")
        choice = decision.get("selected_choice")

        # Werewolf kill targeting a god
        if action == "werewolf_kill" and target is not None:
            target_role = player_roles.get(int(target), "")
            if _is_god(target_role):
                return True

        # Witch save or poison
        if action == "witch_act" and choice:
            return True

        # Exile vote: check if the target was actually exiled
        if action in VOTE_ACTION_TYPES and "exile" in action:
            if target is not None:
                target_role = player_roles.get(int(target), "")
                # Only a turning point if the target was a god or wolf
                if _is_god(target_role) or _is_werewolf(target_role):
                    # Verify the target was actually exiled
                    exiled = any(
                        e.get("event_type") == "death"
                        and e.get("target") == target
                        and (e.get("payload", {}) or {}).get("cause") == "exile"
                        for e in events
                    )
                    if exiled:
                        return True

        # Seer check that found a wolf
        if action == "seer_check" and target is not None:
            target_role = player_roles.get(int(target), "")
            if _is_werewolf(target_role):
                return True

        # Hunter shot
        if action == "hunter_shoot":
            return True

        # White wolf king explosion
        if action == "white_wolf_explode":
            return True

        return False

    # ------------------------------------------------------------------
    # Decision quality judgement
    # ------------------------------------------------------------------

    def _judge_decision(
        self,
        decision: dict,
        events: list[dict],
        player_roles: dict[int, str],
        winner: str,
        player_eval: Any,  # PlayerEvaluation | None
    ) -> tuple[str, str, str | None]:
        """Judge the quality of a turning-point decision.

        Returns (quality, reason, alternative_action).
        quality: 'good', 'bad', or 'questionable'
        """
        action = decision.get("action_type", "")
        seat = _get_seat(decision)
        role = player_roles.get(seat, "unknown")
        target = decision.get("selected_target")
        choice = decision.get("selected_choice")
        target_role = player_roles.get(int(target), "") if target is not None else ""

        # --- Werewolf kill ---
        if action == "werewolf_kill":
            if _is_god(target_role):
                return (
                    "good",
                    f"Wolf P{seat} killed {target_role} P{target}, removing a key god.",
                    None,
                )
            if _is_werewolf(target_role):
                return (
                    "bad",
                    f"Wolf P{seat} killed teammate P{target} ({target_role}).",
                    "Target a non-wolf player instead.",
                )
            return (
                "questionable",
                f"Wolf P{seat} killed villager P{target}; killing a god would be more impactful.",
                "Consider targeting a god role for greater strategic advantage.",
            )

        # --- Witch ---
        if action == "witch_act":
            if str(choice).lower() == "save":
                if _is_good(target_role):
                    return (
                        "good",
                        f"Witch P{seat} saved {target_role} P{target}, preserving a good player.",
                        None,
                    )
                return (
                    "bad",
                    f"Witch P{seat} saved wolf P{target}.",
                    "Verify target identity before using save potion.",
                )
            if str(choice).lower() == "poison":
                if _is_werewolf(target_role):
                    return (
                        "good",
                        f"Witch P{seat} poisoned wolf P{target}, a strong play.",
                        None,
                    )
                return (
                    "bad",
                    f"Witch P{seat} poisoned good player P{target} ({target_role}).",
                    "Avoid poisoning without strong evidence; consider withholding the potion.",
                )

        # --- Exile vote ---
        if action in VOTE_ACTION_TYPES:
            if _is_good(role) and _is_werewolf(target_role):
                return (
                    "good",
                    f"P{seat} ({role}) voted to exile wolf P{target}, a correct read.",
                    None,
                )
            if _is_good(role) and _is_good(target_role):
                return (
                    "bad",
                    f"P{seat} ({role}) voted to exile good player P{target} ({target_role}).",
                    "Re-evaluate suspicion based on seer checks and voting patterns.",
                )
            if _is_werewolf(role) and _is_good(target_role):
                return (
                    "good",
                    f"Wolf P{seat} successfully framed good player P{target} for exile.",
                    None,
                )
            if _is_werewolf(role) and _is_werewolf(target_role):
                return (
                    "bad",
                    f"Wolf P{seat} voted out teammate P{target}.",
                    "Coordinate with wolf team to avoid friendly fire.",
                )

        # --- Seer check ---
        if action == "seer_check":
            if _is_werewolf(target_role):
                return (
                    "good",
                    f"Seer P{seat} checked P{target} and found a wolf. Critical information.",
                    None,
                )
            return (
                "questionable",
                f"Seer P{seat} checked P{target} who is good. Useful but not a turning point.",
                "Try to check players with suspicious behaviour for higher impact.",
            )

        # --- Hunter shot ---
        if action == "hunter_shoot":
            if _is_werewolf(target_role):
                return (
                    "good",
                    f"Hunter P{seat} shot wolf P{target}, a valuable trade.",
                    None,
                )
            if _is_god(target_role):
                return (
                    "bad",
                    f"Hunter P{seat} shot god P{target} ({target_role}), a devastating loss.",
                    "Use voting patterns and speech analysis to identify wolves before shooting.",
                )
            return (
                "questionable",
                f"Hunter P{seat} shot villager P{target}. Not ideal but not catastrophic.",
                "Consider withholding the shot if uncertain.",
            )

        # --- White wolf king explosion ---
        if action == "white_wolf_explode":
            if _team_won(role, winner):
                return (
                    "good",
                    f"White wolf king P{seat} exploded and wolves won the game.",
                    None,
                )
            return (
                "questionable",
                f"White wolf king P{seat} exploded but wolves lost. Timing may have been off.",
                "Consider delaying explosion to gather more information.",
            )

        # Fallback
        return (
            "questionable",
            f"P{seat} ({role}) made a notable {action} decision.",
            None,
        )

    # ------------------------------------------------------------------
    # Counterfactual generation
    # ------------------------------------------------------------------

    def _generate_counterfactual(
        self,
        decision: dict,
        player_roles: dict[int, str],
        winner: str,
        game_id: str,
        decision_id: str,
    ) -> Counterfactual | None:
        """Generate a what-if scenario for a turning-point decision."""
        action = decision.get("action_type", "")
        seat = _get_seat(decision)
        role = player_roles.get(seat, "unknown")
        target = decision.get("selected_target")
        choice = decision.get("selected_choice")
        target_role = player_roles.get(int(target), "") if target is not None else ""

        what_if = ""
        likely_outcome = ""
        confidence = 0.5

        # --- Werewolf kill a god ---
        if action == "werewolf_kill" and _is_god(target_role):
            what_if = (
                f"If wolves had killed a different player instead of "
                f"{target_role} P{target}"
            )
            likely_outcome = (
                f"The {target_role} would have survived and continued "
                f"providing value to the good team. Wolves may have lost "
                f"their information/skill advantage."
            )
            confidence = 0.7

        # --- Witch poison ---
        elif action == "witch_act" and str(choice).lower() == "poison":
            if _is_werewolf(target_role):
                what_if = f"If witch P{seat} had not poisoned wolf P{target}"
                likely_outcome = (
                    "The wolf would have survived and continued threatening "
                    "the good team. Good team may have needed more rounds to "
                    "identify and exile them."
                )
                confidence = 0.65
            else:
                what_if = (
                    f"If witch P{seat} had withheld poison instead of "
                    f"killing good player P{target} ({target_role})"
                )
                likely_outcome = (
                    "The good team would have retained an extra member. "
                    "This likely would have improved the good team's win rate "
                    "by preserving voting power and reducing wolf advantage."
                )
                confidence = 0.75

        # --- Witch save ---
        elif action == "witch_act" and str(choice).lower() == "save":
            what_if = (
                f"If witch P{seat} had not saved P{target} ({target_role})"
            )
            if _is_good(target_role):
                likely_outcome = (
                    f"P{target} ({target_role}) would have died. "
                    f"The good team would have lost a key player and "
                    f"potentially the game."
                )
                confidence = 0.7
            else:
                likely_outcome = (
                    f"Wolf P{target} would have died from the night attack. "
                    f"This would have been beneficial for the good team."
                )
                confidence = 0.6

        # --- Exile vote ---
        elif action in VOTE_ACTION_TYPES:
            if _is_good(role) and _is_werewolf(target_role):
                what_if = (
                    f"If P{seat} had not voted to exile wolf P{target}"
                )
                likely_outcome = (
                    "The wolf would have survived another round, potentially "
                    "killing another good player at night and shifting the "
                    "game balance toward wolves."
                )
                confidence = 0.7
            elif _is_good(role) and _is_good(target_role):
                what_if = (
                    f"If P{seat} had voted correctly instead of exiling "
                    f"good player P{target} ({target_role})"
                )
                likely_outcome = (
                    "A wolf could have been exiled instead. The good team "
                    "would have maintained their numbers advantage and "
                    "gained a significant round lead."
                )
                confidence = 0.65
            else:
                return None

        # --- Seer check ---
        elif action == "seer_check" and _is_werewolf(target_role):
            what_if = (
                f"If seer P{seat} had checked a different player instead "
                f"of wolf P{target}"
            )
            likely_outcome = (
                "The seer might have checked a good player, gaining less "
                "actionable information. The wolf P{target} would have "
                "remained undetected for longer."
            )
            confidence = 0.6

        # --- Hunter shot ---
        elif action == "hunter_shoot":
            if _is_werewolf(target_role):
                what_if = (
                    f"If hunter P{seat} had not shot wolf P{target}"
                )
                likely_outcome = (
                    "The wolf would have survived, maintaining wolf team "
                    "numbers and potentially altering the game outcome."
                )
                confidence = 0.65
            elif _is_god(target_role):
                what_if = (
                    f"If hunter P{seat} had shot a different player "
                    f"instead of god P{target} ({target_role})"
                )
                likely_outcome = (
                    f"The god P{target} would have survived and continued "
                    f"providing value. The hunter might have hit a wolf "
                    f"or at least not damaged the good team."
                )
                confidence = 0.7
            else:
                what_if = (
                    f"If hunter P{seat} had withheld the shot instead of "
                    f"killing P{target}"
                )
                likely_outcome = (
                    "No additional death would have occurred. The game "
                    "state would have been less chaotic."
                )
                confidence = 0.5

        # --- White wolf king explosion ---
        elif action == "white_wolf_explode":
            what_if = (
                f"If white wolf king P{seat} had not exploded"
            )
            likely_outcome = (
                "The game would have continued with the white wolf king "
                "alive, potentially allowing wolves to maintain a numbers "
                "advantage for longer."
            )
            confidence = 0.55

        else:
            return None

        if not what_if:
            return None

        now = beijing_now_iso()
        return Counterfactual(
            id=str(uuid.uuid4()),
            game_id=game_id,
            decision_id=decision_id,
            what_if=what_if,
            likely_outcome=likely_outcome,
            confidence=confidence,
            created_at=now,
        )
