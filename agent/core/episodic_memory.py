"""Cross-game episodic memory persistence.

After each game ends, this module extracts structured records from the
in-game AgentMemory and writes them to the evolution database for
cross-game learning.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from agent.common import beijing_now_iso


# ---------------------------------------------------------------------------
# Role / team mapping (string-based, dependency-light)
# ---------------------------------------------------------------------------

_ROLE_TEAM_MAP: dict[str, str] = {
    "werewolf": "werewolves",
    "white_wolf_king": "werewolves",
    "villager": "villagers",
    "seer": "gods",
    "witch": "gods",
    "hunter": "gods",
    "guard": "gods",
}

#: Roles considered "god" roles (special villagers).
_GOD_ROLES: frozenset[str] = frozenset({"seer", "witch", "hunter", "guard"})

#: Roles on the werewolf side.
_WOLF_ROLES: frozenset[str] = frozenset({"werewolf", "white_wolf_king"})


def _team_for_role(role: str) -> str:
    """Return the team name for a given role string."""
    return _ROLE_TEAM_MAP.get(role, "villagers")


def _team_won(my_team: str, winner: str) -> bool:
    """Return True if *my_team* is on the winning side.

    The winner string is either ``'werewolves'`` or ``'villagers'``.
    When villagers win, gods also win (they share the good side).
    """
    if winner == "werewolves":
        return my_team == "werewolves"
    # winner == 'villagers' — both villagers and gods win
    return my_team in ("villagers", "gods")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class SituationalRecord:
    """Snapshot of a game situation from one player's perspective."""

    id: str
    game_id: str
    role: str
    seat: int
    day: int | None
    phase: str | None
    alive_players: list[int]
    key_events: list[dict[str, Any]]
    outcome: str  # 'win' or 'loss'
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict suitable for JSON storage."""
        return {
            "id": self.id,
            "game_id": self.game_id,
            "role": self.role,
            "seat": self.seat,
            "day": self.day,
            "phase": self.phase,
            "alive_players": list(self.alive_players),
            "key_events": list(self.key_events),
            "outcome": self.outcome,
            "created_at": self.created_at,
        }


@dataclass
class DecisionOutcome:
    """Post-game quality label for a single decision."""

    decision_id: str
    game_id: str
    player_seat: int
    role: str
    action_type: str
    day: int
    phase: str
    quality: str  # 'good', 'bad', 'neutral', 'uncertain'
    reason: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict suitable for JSON storage."""
        return {
            "decision_id": self.decision_id,
            "game_id": self.game_id,
            "player_seat": self.player_seat,
            "role": self.role,
            "action_type": self.action_type,
            "day": self.day,
            "phase": self.phase,
            "quality": self.quality,
            "reason": self.reason,
            "created_at": self.created_at,
        }


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------


class EpisodicMemoryWriter:
    """Extracts and persists structured memory records after a game ends."""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def persist_game(
        self,
        game_id: str,
        *,
        player_memories: dict[int, Any],  # player_id -> AgentMemory
        player_roles: dict[int, str],  # player_id -> role string
        winner: str,  # 'werewolves' or 'villagers'
        decisions: list[dict[str, Any]],  # raw decision records
        game_events: list[dict[str, Any]],  # game event log
    ) -> tuple[list[SituationalRecord], list[DecisionOutcome]]:
        """Extract structured records from a completed game.

        1. For each player, create a :class:`SituationalRecord` from their
           final memory state.
        2. For each decision, create a :class:`DecisionOutcome` by labeling
           quality.
        3. Return both lists (caller writes to DB).
        """
        situational_records: list[SituationalRecord] = []
        for player_id, memory in player_memories.items():
            role = player_roles.get(player_id, "villager")
            my_team = _team_for_role(role)
            outcome = "win" if _team_won(my_team, winner) else "loss"
            record = self._extract_situational_record(
                game_id, player_id, memory, role, outcome,
            )
            situational_records.append(record)

        decision_outcomes: list[DecisionOutcome] = []
        for decision in decisions:
            player_id = decision.get("player_id")
            if player_id is None:
                continue
            role = player_roles.get(player_id, decision.get("role", "villager"))
            outcome = self.label_decision(
                decision,
                game_id=game_id,
                player_role=role,
                winner=winner,
                game_events=game_events,
                player_roles=player_roles,
            )
            decision_outcomes.append(outcome)

        return situational_records, decision_outcomes

    # ------------------------------------------------------------------
    # Situational record extraction
    # ------------------------------------------------------------------

    def _extract_situational_record(
        self,
        game_id: str,
        player_id: int,
        memory: Any,  # AgentMemory
        role: str,
        outcome: str,
    ) -> SituationalRecord:
        """Extract a :class:`SituationalRecord` from an AgentMemory's final state."""
        # Alive players from field_notes.game_state
        game_state = getattr(memory, "field_notes", None)
        alive_players: list[int] = []
        last_day: int | None = None
        last_phase: str | None = None

        if game_state is not None:
            gs = getattr(game_state, "game_state", {}) or {}
            alive_players = list(gs.get("alive_players", []))
            last_day = gs.get("day")
            last_phase = gs.get("phase")

        # Fallback: try to infer last day/phase from events list
        if last_day is None:
            events = getattr(memory, "events", [])
            if events:
                last_event = events[-1]
                last_day = getattr(last_event, "day", None)
                last_phase = getattr(last_event, "phase", None)

        # Key events from pinned_facts, stripping internal _stable_key
        key_events: list[dict[str, Any]] = []
        pinned_facts = getattr(memory, "pinned_facts", [])
        for fact in pinned_facts:
            cleaned = {k: v for k, v in fact.items() if k != "_stable_key"}
            key_events.append(cleaned)

        return SituationalRecord(
            id=str(uuid.uuid4()),
            game_id=game_id,
            role=role,
            seat=player_id,
            day=last_day,
            phase=last_phase,
            alive_players=alive_players,
            key_events=key_events,
            outcome=outcome,
            created_at=beijing_now_iso(),
        )

    # ------------------------------------------------------------------
    # Decision labeling
    # ------------------------------------------------------------------

    def label_decision(
        self,
        decision: dict[str, Any],
        *,
        game_id: str = "",
        player_role: str,
        winner: str,
        game_events: list[dict[str, Any]],
        player_roles: dict[int, str],
    ) -> DecisionOutcome:
        """Label a single decision's quality based on outcome alignment.

        Rules
        -----
        - If the decision's team won and the action helped -> ``'good'``
        - If the decision's team lost and the action hurt -> ``'bad'``
        - Otherwise -> ``'neutral'`` or ``'uncertain'``

        Role-specific rules
        -------------------
        - **Seer**: checking a wolf = good signal, checking villager = neutral
        - **Witch**: saving a god = good, poisoning teammate = bad
        - **Werewolf**: killing seer/god = good (for wolves), killing random = neutral
        - **Guard**: protecting someone who was attacked = good
        - **Villager**: voting out a wolf = good, voting out teammate = bad
        """
        decision_id = str(decision.get("decision_id", ""))
        player_id = decision.get("player_id", 0)
        action_type = str(decision.get("action_type", ""))
        day = int(decision.get("day", 0))
        phase = str(decision.get("phase", ""))
        selected_target = decision.get("selected_target")
        selected_choice = decision.get("selected_choice")

        my_team = _team_for_role(player_role)
        won = _team_won(my_team, winner)

        # Determine the target's role and team (if applicable)
        target_role: str | None = None
        target_team: str | None = None
        if selected_target is not None and selected_target in player_roles:
            target_role = player_roles[selected_target]
            target_team = _team_for_role(target_role)

        # Attempt role-specific heuristic first
        quality, reason = self._apply_role_heuristic(
            action_type=action_type,
            player_role=player_role,
            my_team=my_team,
            selected_target=selected_target,
            selected_choice=selected_choice,
            target_role=target_role,
            target_team=target_team,
            won=won,
            winner=winner,
            game_events=game_events,
            day=day,
        )

        # If the heuristic returned uncertain, fall back to generic outcome-based
        if quality == "uncertain":
            quality, reason = self._generic_label(
                action_type=action_type,
                won=won,
                my_team=my_team,
                target_team=target_team,
                player_role=player_role,
            )

        return DecisionOutcome(
            decision_id=decision_id,
            game_id=game_id,
            player_seat=int(player_id),
            role=player_role,
            action_type=action_type,
            day=day,
            phase=phase,
            quality=quality,
            reason=reason,
            created_at=beijing_now_iso(),
        )

    # ------------------------------------------------------------------
    # Role-specific heuristics
    # ------------------------------------------------------------------

    def _apply_role_heuristic(
        self,
        *,
        action_type: str,
        player_role: str,
        my_team: str,
        selected_target: int | None,
        selected_choice: str | None,
        target_role: str | None,
        target_team: str | None,
        won: bool,
        winner: str,
        game_events: list[dict[str, Any]],
        day: int,
    ) -> tuple[str, str]:
        """Apply role-specific decision quality heuristics.

        Returns ``(quality, reason)``.  If no heuristic applies, returns
        ``('uncertain', '')`` so the caller can fall back.
        """
        # ----- Seer -----
        if player_role == "seer" and action_type == "seer_check":
            if target_role is not None:
                if target_team == "werewolves":
                    return "good", "查验到狼人，为好人阵营提供了关键信息"
                if target_team in ("villagers", "gods"):
                    return "neutral", "查验到好人，信息价值有限"
            return "uncertain", ""

        # ----- Witch -----
        if player_role == "witch" and action_type == "witch_act":
            # Witch has two abilities: save (choice='save') and poison (choice='poison')
            if selected_choice == "save":
                if target_role is not None and target_team in ("gods",):
                    return "good", "救了神职，保护了关键角色"
                if target_role is not None and target_team == "werewolves":
                    return "bad", "救了狼人，浪费了药水"
                if target_role is not None and target_team == "villagers":
                    return "good", "救了村民，保存了好人阵营人数"
                return "neutral", "使用了解药"
            if selected_choice == "poison":
                if target_role is not None and target_team == "werewolves":
                    return "good", "毒杀了狼人，削弱了狼人阵营"
                if target_role is not None and target_team in ("villagers", "gods"):
                    return "bad", "毒杀了队友，削弱了好人阵营"
                return "uncertain", ""

        # ----- Werewolf -----
        if player_role in ("werewolf", "white_wolf_king") and action_type == "werewolf_kill":
            if target_role is not None:
                if target_role in _GOD_ROLES:
                    return "good", "击杀了神职，削弱了好人阵营"
                if target_team == "villagers":
                    return "neutral", "击杀了普通村民"
                if target_team == "werewolves":
                    return "bad", "误杀了队友"
            return "uncertain", ""

        # ----- Guard -----
        if player_role == "guard" and action_type == "guard_protect":
            if selected_target is not None:
                # Check if the protected player was attacked that night
                attacked = self._was_target_attacked(selected_target, game_events, day)
                if attacked:
                    return "good", "成功保护了被袭击的玩家"
                if target_role is not None and target_role in _GOD_ROLES:
                    return "neutral", "保护了神职（未被袭击）"
                return "neutral", "保护了玩家（未被袭击）"
            return "uncertain", ""

        # ----- Hunter -----
        if player_role == "hunter" and action_type == "hunter_shoot":
            if target_role is not None:
                if target_team == "werewolves":
                    return "good", "猎人带走了狼人"
                if target_team in ("villagers", "gods"):
                    return "bad", "猎人带走了队友"
            return "uncertain", ""

        # ----- Exile vote (any role) -----
        if action_type in ("exile_vote", "pk_vote"):
            if target_role is not None:
                target_is_wolf = target_team == "werewolves"
                i_am_wolf = my_team == "werewolves"
                if target_is_wolf and not i_am_wolf:
                    return "good", "投票放逐了狼人"
                if not target_is_wolf and not i_am_wolf:
                    return "bad", "投票放逐了队友"
                if target_is_wolf and i_am_wolf:
                    return "bad", "作为狼人投票放逐了队友"
                if not target_is_wolf and i_am_wolf:
                    return "good", "作为狼人成功放逐了好人"
            return "uncertain", ""

        # ----- White wolf explode -----
        if player_role == "white_wolf_king" and action_type == "white_wolf_explode":
            if target_role is not None:
                if target_role in _GOD_ROLES:
                    return "good", "白狼王带走了关键神职"
                if target_team == "villagers":
                    return "neutral", "白狼王带走了普通村民"
                if target_team == "werewolves":
                    return "bad", "白狼王误带了队友"
            return "uncertain", ""

        # ----- Sheriff actions — generally neutral -----
        if action_type in ("sheriff_run", "sheriff_speak", "sheriff_withdraw",
                           "sheriff_vote", "sheriff_badge", "speech_order"):
            return "neutral", "竞选/发言类行为，不直接影响胜负"

        # ----- Speech actions — hard to evaluate automatically -----
        if action_type in ("speak", "pk_speak", "last_word"):
            return "uncertain", ""

        return "uncertain", ""

    # ------------------------------------------------------------------
    # Generic fallback labeling
    # ------------------------------------------------------------------

    def _generic_label(
        self,
        *,
        action_type: str,
        won: bool,
        my_team: str,
        target_team: str | None,
        player_role: str,
    ) -> tuple[str, str]:
        """Fallback labeling when role-specific heuristics do not apply."""
        # If there is a target and we can assess team alignment
        if target_team is not None:
            is_helpful = self._is_good_for_team(action_type, target_team, player_role, my_team)
            if is_helpful == "good":
                if won:
                    return "good", "行为对己方有利且最终获胜"
                return "neutral", "行为对己方有利但最终落败"
            if is_helpful == "bad":
                if not won:
                    return "bad", "行为对己方不利且最终落败"
                return "neutral", "行为对己方不利但最终获胜"

        # No target information — simple outcome-based
        if won:
            return "neutral", "最终获胜"
        return "neutral", "最终落败"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _is_good_for_team(
        self,
        action_type: str,
        target_team: str | None,
        my_role: str,
        my_team: str,
    ) -> str:
        """Determine if an action was beneficial for the agent's team.

        Parameters
        ----------
        action_type:
            The string action type (e.g. ``'exile_vote'``).
        target_team:
            The team of the target player, or ``None`` if unknown.
        my_role:
            The role string of the acting player.
        my_team:
            The team string of the acting player.

        Returns
        -------
        str
            ``'good'``, ``'bad'``, or ``'neutral'``.
        """
        if target_team is None:
            return "neutral"

        # Vote-type actions: targeting the opposing team is good
        if action_type in ("exile_vote", "pk_vote", "sheriff_vote"):
            if my_team == "werewolves":
                # Wolves want to eliminate villagers/gods
                return "good" if target_team != "werewolves" else "bad"
            # Good team wants to eliminate wolves
            return "good" if target_team == "werewolves" else "bad"

        # Night kill actions (werewolf perspective)
        if action_type == "werewolf_kill":
            if my_team == "werewolves":
                return "good" if target_team != "werewolves" else "bad"
            return "neutral"

        # Seer check — information value
        if action_type == "seer_check":
            if my_team != "werewolves":
                # Finding a wolf is valuable information
                return "good" if target_team == "werewolves" else "neutral"
            return "neutral"

        # Guard protect
        if action_type == "guard_protect":
            # Protecting a teammate is generally good
            if target_team in ("villagers", "gods") and my_team != "werewolves":
                return "good"
            if target_team == "werewolves":
                return "bad"
            return "neutral"

        # Hunter shoot
        if action_type == "hunter_shoot":
            if my_team != "werewolves":
                return "good" if target_team == "werewolves" else "bad"
            return "good" if target_team != "werewolves" else "bad"

        # Witch actions depend on choice, which isn't available here
        if action_type == "white_wolf_explode":
            if my_team == "werewolves":
                return "good" if target_team != "werewolves" else "bad"
            return "neutral"

        return "neutral"

    @staticmethod
    def _was_target_attacked(
        target: int,
        game_events: list[dict[str, Any]],
        day: int,
    ) -> bool:
        """Check if *target* was attacked on the given *day* in the game events."""
        for event in game_events:
            event_type = event.get("type") or event.get("event_type", "")
            event_day = event.get("day", 0)
            event_target = event.get("target")
            # Match death-by-werewolf or general attack events
            if event_target == target and event_day == day:
                if event_type in ("death", "werewolf_result", "werewolf_kill"):
                    return True
            # Also check payload for attack info
            payload = event.get("payload", {})
            if isinstance(payload, dict):
                if payload.get("target") == target and event_day == day:
                    if event_type in ("werewolf_result", "werewolf_kill", "death"):
                        return True
        return False
