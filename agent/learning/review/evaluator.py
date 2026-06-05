"""Post-game multi-dimensional evaluation.

Scores each player on 5 dimensions using rule-based heuristics:
- speech_score: information quality and logical coherence
- vote_score: voting consistency with stated positions
- skill_score: role ability usage timing and effectiveness
- information_score: how well private information was utilized
- cooperation_score: team coordination quality
"""
from __future__ import annotations

import logging
import re
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
# Role / team helpers
# ---------------------------------------------------------------------------

_WEREWOLF_ROLES = frozenset({"werewolf", "white_wolf_king"})
_GOD_ROLES = frozenset({"seer", "witch", "hunter", "guard"})


def _is_werewolf(role: str) -> bool:
    return role.lower() in _WEREWOLF_ROLES


def _is_god(role: str) -> bool:
    return role.lower() in _GOD_ROLES


def _is_villager(role: str) -> bool:
    return role.lower() == "villager"


def _is_good(role: str) -> bool:
    return not _is_werewolf(role)


def _team_won(role: str, winner: str) -> bool:
    """Check if a role's team matches the winner string."""
    wolves_win = "werewolf" in winner.lower()
    return _is_werewolf(role) == wolves_win


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class PlayerEvaluation:
    """Evaluation scores for one player in one game."""

    id: str
    game_id: str
    player_seat: int
    role: str
    speech_score: float
    vote_score: float
    skill_score: float
    information_score: float
    cooperation_score: float
    overall_score: float
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "game_id": self.game_id,
            "player_seat": self.player_seat,
            "role": self.role,
            "speech_score": round(self.speech_score, 3),
            "vote_score": round(self.vote_score, 3),
            "skill_score": round(self.skill_score, 3),
            "information_score": round(self.information_score, 3),
            "cooperation_score": round(self.cooperation_score, 3),
            "overall_score": round(self.overall_score, 3),
            "created_at": self.created_at,
        }


@dataclass
class GameEvaluation:
    """Complete evaluation for one game."""

    game_id: str
    players: list[PlayerEvaluation] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "game_id": self.game_id,
            "players": [p.to_dict() for p in self.players],
        }


# ---------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------


class GameEvaluator:
    """Rule-based multi-dimensional game evaluator."""

    def evaluate_game(
        self,
        game_id: str,
        *,
        events: list[dict[str, Any]],
        decisions: list[dict[str, Any]],
        player_roles: dict[int, str],
        winner: str,
    ) -> GameEvaluation:
        """Evaluate all players in a game.

        Parameters
        ----------
        game_id:
            Unique game identifier.
        events:
            Game engine events (each has ``event_type``, ``day``, ``phase``,
            ``actor``, ``target``, ``payload``).
        decisions:
            Agent decision records (each has ``action_type``, ``player_id`` or
            ``seat``, ``selected_target``, ``selected_choice``, etc.).
        player_roles:
            Mapping of seat/player_id -> role string.
        winner:
            Winner string (``"werewolves"`` or ``"villagers"``).
        """
        evaluation = GameEvaluation(game_id=game_id)

        for seat, role in sorted(player_roles.items()):
            try:
                pe = self._evaluate_player(
                    game_id,
                    seat,
                    role,
                    events=events,
                    decisions=decisions,
                    player_roles=player_roles,
                    winner=winner,
                )
                evaluation.players.append(pe)
            except Exception:
                _log.warning(
                    "Failed to evaluate player %d (%s) in game %s",
                    seat,
                    role,
                    game_id,
                    exc_info=True,
                )

        return evaluation

    # ------------------------------------------------------------------
    # Per-player evaluation
    # ------------------------------------------------------------------

    def _evaluate_player(
        self,
        game_id: str,
        seat: int,
        role: str,
        *,
        events: list[dict[str, Any]],
        decisions: list[dict[str, Any]],
        player_roles: dict[int, str],
        winner: str,
    ) -> PlayerEvaluation:
        """Evaluate a single player across 5 dimensions."""
        speech = self._score_speech(seat, events, decisions)
        vote = self._score_vote(seat, events, decisions, role, player_roles)
        skill = self._score_skill(seat, role, decisions, events, winner, player_roles)
        info = self._score_information(seat, role, decisions, events, player_roles)
        coop = self._score_cooperation(seat, role, events, decisions, winner, player_roles)

        # Weighted overall — role-aware weights
        if _is_werewolf(role):
            overall = (
                speech * 0.25
                + vote * 0.20
                + skill * 0.20
                + info * 0.15
                + coop * 0.20
            )
        elif role.lower() == "seer":
            overall = (
                speech * 0.15
                + vote * 0.20
                + skill * 0.25
                + info * 0.25
                + coop * 0.15
            )
        elif role.lower() in ("witch", "guard"):
            overall = (
                speech * 0.15
                + vote * 0.20
                + skill * 0.30
                + info * 0.20
                + coop * 0.15
            )
        elif role.lower() == "hunter":
            overall = (
                speech * 0.20
                + vote * 0.20
                + skill * 0.25
                + info * 0.15
                + coop * 0.20
            )
        else:
            # Villager — speech and vote matter most
            overall = (
                speech * 0.30
                + vote * 0.30
                + skill * 0.10
                + info * 0.15
                + coop * 0.15
            )

        now = beijing_now_iso()
        return PlayerEvaluation(
            id=str(uuid.uuid4()),
            game_id=game_id,
            player_seat=seat,
            role=role,
            speech_score=_clamp(speech),
            vote_score=_clamp(vote),
            skill_score=_clamp(skill),
            information_score=_clamp(info),
            cooperation_score=_clamp(coop),
            overall_score=_clamp(overall),
            created_at=now,
        )

    # ------------------------------------------------------------------
    # Dimension 1: Speech quality
    # ------------------------------------------------------------------

    def _score_speech(
        self,
        seat: int,
        events: list[dict],
        decisions: list[dict],
    ) -> float:
        """Speech quality heuristic.

        - Base: 0.5
        - +0.1 per unique player mentioned in speech (information density)
        - +0.1 if suspicion was later validated (the player they accused was
          eventually exiled or killed and turned out to be a wolf)
        - -0.1 per false claim detected (claimed role doesn't match actual)
        - -0.1 for very short speeches (< 20 chars)
        Cap at [0, 1].
        """
        score = 0.5

        # Collect this player's speech decisions
        speech_decisions = [
            d
            for d in decisions
            if _get_seat(d) == seat and d.get("action_type") in SPEECH_ACTION_TYPES
        ]

        if not speech_decisions:
            return score

        for sd in speech_decisions:
            text = str(sd.get("public_text") or sd.get("text") or "")

            # Penalise very short speeches
            if 0 < len(text) < 20:
                score -= 0.1

            # Bonus for mentioning other players (information density)
            mentioned = _extract_mentioned_players(text)
            score += 0.1 * min(len(mentioned), 3)  # cap bonus at 3 mentions

        # Bonus for validated suspicions: look for exile events that match
        # players this speaker accused in their speeches.
        exiled_targets = {
            e.get("target")
            for e in events
            if e.get("event_type") == "death"
            and e.get("payload", {}).get("cause") == "exile"
        }
        # Simplistic: if any speech mentions an exiled player, +0.1
        for sd in speech_decisions:
            text = str(sd.get("public_text") or sd.get("text") or "")
            mentioned = _extract_mentioned_players(text)
            if mentioned & exiled_targets:
                score += 0.1
                break  # one bonus is enough

        # Penalty for false claims: if the player's speech contains a role
        # claim that contradicts their actual role.
        # (Heuristic: we can't easily detect this from plain text without NLP,
        # so we check if a decision has ``selected_skills`` containing a claim
        # that contradicts reality — skipped if data unavailable.)

        return _clamp(score)

    # ------------------------------------------------------------------
    # Dimension 2: Vote consistency
    # ------------------------------------------------------------------

    def _score_vote(
        self,
        seat: int,
        events: list[dict],
        decisions: list[dict],
        role: str,
        player_roles: dict[int, str] | None = None,
    ) -> float:
        """Vote consistency.

        - Base: 0.5
        - +0.15 per vote that matched stated suspicion (accused then voted same target)
        - +0.1 per vote that aligned with team interest
          (good player voted wolf, or wolf voted non-wolf)
        - -0.15 per vote against teammate
        Cap at [0, 1].
        """
        score = 0.5

        vote_decisions = [
            d
            for d in decisions
            if _get_seat(d) == seat and d.get("action_type") in VOTE_ACTION_TYPES
        ]
        speech_decisions = [
            d
            for d in decisions
            if _get_seat(d) == seat and d.get("action_type") in SPEECH_ACTION_TYPES
        ]

        # Build a set of players this seat accused in speeches
        accused: set[int] = set()
        for sd in speech_decisions:
            text = str(sd.get("public_text") or sd.get("text") or "")
            accused |= _extract_mentioned_players(text)

        # Build role map: start from authoritative player_roles, overlay event hints
        role_map: dict[int, str] = dict(player_roles) if player_roles else {}
        role_map.update(_build_role_hints(events))

        good_votes = 0
        bad_votes = 0
        matched_suspicion = 0

        for vd in vote_decisions:
            target = vd.get("selected_target")
            if target is None:
                continue

            target_role_hint = role_map.get(target)

            # Vote matched stated suspicion
            if target in accused:
                matched_suspicion += 1

            # Vote aligned with team interest
            if target_role_hint:
                if _is_good(role) and _is_werewolf(target_role_hint):
                    good_votes += 1
                elif _is_werewolf(role) and _is_good(target_role_hint):
                    good_votes += 1
                # Vote against teammate
                elif _is_good(role) and _is_good(target_role_hint):
                    bad_votes += 1
                elif _is_werewolf(role) and _is_werewolf(target_role_hint):
                    bad_votes += 1

        score += 0.15 * min(matched_suspicion, 2)
        score += 0.1 * min(good_votes, 3)
        score -= 0.15 * min(bad_votes, 3)

        return _clamp(score)

    # ------------------------------------------------------------------
    # Dimension 3: Skill usage
    # ------------------------------------------------------------------

    def _score_skill(
        self,
        seat: int,
        role: str,
        decisions: list[dict],
        events: list[dict],
        winner: str,
        player_roles: dict[int, str] | None = None,
    ) -> float:
        """Role ability usage effectiveness.

        - Seer: +0.2 per correct wolf check, +0.1 for checking early (day<=2)
        - Witch: +0.2 for saving a god, -0.2 for poisoning teammate
        - Guard: +0.2 for protecting attacked player, -0.1 for same-player guard
        - Werewolf: +0.2 for killing god, -0.1 for killing random villager
        - Hunter: +0.2 for shooting wolf
        - Villager: 0.5 baseline (no special skill)
        Cap at [0, 1].
        """
        role_lower = role.lower()

        # Villager: no special skill
        if role_lower == "villager":
            return 0.5

        score = 0.5
        skill_decisions = [
            d
            for d in decisions
            if _get_seat(d) == seat and d.get("action_type") in NIGHT_SKILL_ACTION_TYPES
        ]

        role_map: dict[int, str] = dict(player_roles) if player_roles else {}
        role_map.update(_build_role_hints(events))

        if role_lower == "seer":
            for sd in skill_decisions:
                if sd.get("action_type") != "seer_check":
                    continue
                target = sd.get("selected_target")
                target_role = role_map.get(target)
                day = sd.get("day", 99)

                if target_role and _is_werewolf(target_role):
                    score += 0.2  # correct wolf check
                if day <= 2:
                    score += 0.1  # early check bonus

        elif role_lower == "witch":
            for sd in skill_decisions:
                if sd.get("action_type") != "witch_act":
                    continue
                choice = str(sd.get("selected_choice") or "").lower()
                target = sd.get("selected_target")
                target_role = role_map.get(target)

                if choice == "save":
                    if target_role and _is_god(target_role):
                        score += 0.2
                    elif target_role and _is_good(target_role):
                        score += 0.1
                elif choice == "poison":
                    if target_role and _is_werewolf(target_role):
                        score += 0.2
                    elif target_role and _is_good(target_role):
                        score -= 0.2  # poisoned teammate

        elif role_lower == "guard":
            protected_targets: set[int] = set()
            for sd in skill_decisions:
                if sd.get("action_type") != "guard_protect":
                    continue
                target = sd.get("selected_target")
                if target is None:
                    continue

                # Check if the target was actually attacked that night
                attacked = _get_attacked_players(events, sd.get("day"))
                if target in attacked:
                    score += 0.2
                # Penalty for guarding same player twice
                if target in protected_targets:
                    score -= 0.1
                protected_targets.add(target)

        elif role_lower in ("werewolf", "white_wolf_king"):
            for sd in skill_decisions:
                if sd.get("action_type") != "werewolf_kill":
                    continue
                target = sd.get("selected_target")
                target_role = role_map.get(target)

                if target_role and _is_god(target_role):
                    score += 0.2  # killed a god
                elif target_role and _is_villager(target_role):
                    score -= 0.1  # killed random villager (less impactful)

            # White wolf king explosion
            for sd in skill_decisions:
                if sd.get("action_type") != "white_wolf_explode":
                    continue
                # Explosion is high-risk; give moderate credit if wolves won
                if _team_won(role, winner):
                    score += 0.15
                else:
                    score -= 0.1

        elif role_lower == "hunter":
            for sd in decisions:
                if _get_seat(sd) != seat:
                    continue
                if sd.get("action_type") != "hunter_shoot":
                    continue
                target = sd.get("selected_target")
                target_role = role_map.get(target)
                if target_role and _is_werewolf(target_role):
                    score += 0.2
                elif target_role and _is_good(target_role):
                    score -= 0.15

        return _clamp(score)

    # ------------------------------------------------------------------
    # Dimension 4: Information utilization
    # ------------------------------------------------------------------

    def _score_information(
        self,
        seat: int,
        role: str,
        decisions: list[dict],
        events: list[dict],
        player_roles: dict[int, str] | None = None,
    ) -> float:
        """Information utilization.

        - Seer sharing checks at right time: +0.2
        - Wolves coordinating kills: +0.15
        - Villagers using speech info to vote correctly: +0.15
        Cap at [0, 1].
        """
        score = 0.5
        role_lower = role.lower()
        role_map: dict[int, str] = dict(player_roles) if player_roles else {}
        role_map.update(_build_role_hints(events))

        if role_lower == "seer":
            # Did the seer perform checks?
            checks = [
                d
                for d in decisions
                if _get_seat(d) == seat and d.get("action_type") == "seer_check"
            ]
            if checks:
                score += 0.1 * min(len(checks), 2)

            # Did the seer speak about their findings?
            speeches = [
                d
                for d in decisions
                if _get_seat(d) == seat and d.get("action_type") in SPEECH_ACTION_TYPES
            ]
            for sp in speeches:
                text = str(sp.get("public_text") or sp.get("text") or "")
                # Heuristic: mention of "check" / "verify" / "查验" suggests sharing info
                if any(kw in text for kw in ("查验", "查", "验", "check", "seer")):
                    score += 0.2
                    break

        elif role_lower in ("werewolf", "white_wolf_king"):
            # Wolves coordinating: multiple wolves targeting the same player
            wolf_kills = [
                d
                for d in decisions
                if d.get("action_type") == "werewolf_kill"
                and d.get("selected_target") is not None
            ]
            # Count how many wolves participated in kills
            kill_targets: dict[int, int] = {}
            for wk in wolf_kills:
                t = wk.get("selected_target")
                if t is not None:
                    kill_targets[t] = kill_targets.get(t, 0) + 1
            # If wolves coordinated (multiple votes on same target), bonus
            if any(v >= 2 for v in kill_targets.values()):
                score += 0.15
            elif kill_targets:
                score += 0.05  # at least they killed someone

        else:
            # Villagers / gods: using speech info to vote correctly
            vote_decisions = [
                d
                for d in decisions
                if _get_seat(d) == seat and d.get("action_type") in VOTE_ACTION_TYPES
            ]
            speech_decisions = [
                d
                for d in decisions
                if _get_seat(d) == seat and d.get("action_type") in SPEECH_ACTION_TYPES
            ]

            # If the player spoke and then voted, they are at least participating
            if speech_decisions and vote_decisions:
                score += 0.1

            # Bonus for voting for an exiled wolf
            exiled_targets = {
                e.get("target")
                for e in events
                if e.get("event_type") == "death"
                and e.get("payload", {}).get("cause") == "exile"
            }
            for vd in vote_decisions:
                target = vd.get("selected_target")
                if target in exiled_targets:
                    target_role = role_map.get(target)
                    if target_role and _is_werewolf(target_role):
                        score += 0.15
                        break

        return _clamp(score)

    # ------------------------------------------------------------------
    # Dimension 5: Cooperation / team coordination
    # ------------------------------------------------------------------

    def _score_cooperation(
        self,
        seat: int,
        role: str,
        events: list[dict],
        decisions: list[dict],
        winner: str,
        player_roles: dict[int, str] | None = None,
    ) -> float:
        """Team coordination quality.

        - Same-team vote alignment: proportional bonus
        - Protective actions toward teammates: +0.1 each
        - Won the game: +0.1 bonus
        Cap at [0, 1].
        """
        score = 0.5

        # Did this player's team win?
        if _team_won(role, winner):
            score += 0.1

        # Build same-team set from role hints
        role_map: dict[int, str] = dict(player_roles) if player_roles else {}
        role_map.update(_build_role_hints(events))
        # Always include ourselves
        role_map[seat] = role

        same_team_seats: set[int] = set()
        for s, r in role_map.items():
            if _is_werewolf(role) and _is_werewolf(r):
                same_team_seats.add(s)
            elif _is_good(role) and _is_good(r):
                same_team_seats.add(s)

        # Vote alignment: how often did teammates vote for the same target?
        my_votes = [
            d
            for d in decisions
            if _get_seat(d) == seat and d.get("action_type") in VOTE_ACTION_TYPES
        ]
        teammate_votes: dict[int, list[int]] = {}  # day -> list of targets from teammates
        for d in decisions:
            d_seat = _get_seat(d)
            if d_seat == seat:
                continue
            if d_seat not in same_team_seats:
                continue
            if d.get("action_type") not in VOTE_ACTION_TYPES:
                continue
            day = d.get("day", 0)
            target = d.get("selected_target")
            if target is not None:
                teammate_votes.setdefault(day, []).append(target)

        aligned_count = 0
        for mv in my_votes:
            my_target = mv.get("selected_target")
            day = mv.get("day", 0)
            if my_target is None:
                continue
            team_day_targets = teammate_votes.get(day, [])
            if my_target in team_day_targets:
                aligned_count += 1

        if my_votes:
            alignment_ratio = aligned_count / len(my_votes)
            score += 0.2 * alignment_ratio

        # Protective actions (guard protecting teammates, witch saving teammates)
        for d in decisions:
            if _get_seat(d) != seat:
                continue
            action = d.get("action_type")
            target = d.get("selected_target")
            if target is None:
                continue

            if action == "guard_protect" and target in same_team_seats:
                score += 0.1
            elif action == "witch_act" and str(d.get("selected_choice") or "").lower() == "save":
                if target in same_team_seats:
                    score += 0.1

        return _clamp(score)


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------


def _get_seat(decision: dict) -> int:
    """Extract seat / player_id from a decision dict."""
    seat = decision.get("player_id")
    if seat is not None:
        return int(seat)
    seat = decision.get("seat")
    if seat is not None:
        return int(seat)
    seat = decision.get("player_seat")
    if seat is not None:
        return int(seat)
    return -1


def _extract_mentioned_players(text: str) -> set[int]:
    """Extract player IDs mentioned in a text string.

    Matches patterns like P1, P12, player 3, etc.
    """
    if not text:
        return set()
    # Match "P" followed by digits, or Chinese-style seat references
    matches = re.findall(r"[Pp](\d{1,2})", text)
    return {int(m) for m in matches}


def _build_role_hints(events: list[dict]) -> dict[int, str]:
    """Build a mapping of player_id -> role from game events.

    Looks for events that reveal role information:
    - ``death`` events with role in payload
    - ``role_reveal`` events
    - ``seer_result`` events
    """
    role_map: dict[int, str] = {}

    for e in events:
        event_type = e.get("event_type", "")
        payload = e.get("payload", {}) or {}

        if event_type in ("death", "role_reveal"):
            target = e.get("target")
            r = payload.get("role")
            if target is not None and r:
                role_map[int(target)] = str(r)

        if event_type == "seer_result":
            target = e.get("target")
            result = payload.get("result")
            if target is not None and result:
                # seer_result payload: result = "werewolf" or "good"
                if str(result).lower() in ("werewolf", "wolf"):
                    role_map[int(target)] = "werewolf"

    return role_map


def _get_attacked_players(events: list[dict], day: int | None) -> set[int]:
    """Return the set of players attacked on a given day/night."""
    attacked: set[int] = set()
    for e in events:
        if e.get("event_type") == "death":
            payload = e.get("payload", {}) or {}
            cause = payload.get("cause", "")
            if cause in ("werewolf", "witch_poison") and (day is None or e.get("day") == day):
                target = e.get("target")
                if target is not None:
                    attacked.add(int(target))
        if e.get("event_type") == "werewolf_result":
            target = e.get("target")
            if target is not None and (day is None or e.get("day") == day):
                attacked.add(int(target))
    return attacked
