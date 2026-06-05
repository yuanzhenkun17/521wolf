"""Structured game report generation.

Produces a ``GameReport`` combining evaluation scores, decision reviews,
counterfactuals, and timeline events into a single structured document
suitable for persistence and human review.
"""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from agent.common import beijing_now_iso

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Role / team helpers
# ---------------------------------------------------------------------------

_WEREWOLF_ROLES = frozenset({"werewolf", "white_wolf_king"})


def _is_werewolf(role: str) -> bool:
    return role.lower() in _WEREWOLF_ROLES


def _team_label(role: str) -> str:
    return "werewolves" if _is_werewolf(role) else "villagers"


def _get_seat(decision: dict) -> int:
    for key in ("player_id", "seat", "player_seat"):
        v = decision.get(key)
        if v is not None:
            return int(v)
    return -1


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class GameReport:
    """Structured report for one completed game."""

    id: str
    game_id: str
    summary: dict[str, Any]
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "game_id": self.game_id,
            "summary": self.summary,
            "created_at": self.created_at,
        }

    def to_json(self) -> str:
        """Serialize to JSON string (suitable for ReportStore.save_report)."""
        return json.dumps(self.summary, ensure_ascii=False, indent=2)

    def to_markdown(self) -> str:
        """Render the report as a Markdown document."""
        s = self.summary
        lines: list[str] = []

        # Header
        lines.append(f"# Game Report: {self.game_id}")
        lines.append("")
        lines.append(f"**Winner**: {s.get('winner', 'unknown')}  ")
        lines.append(f"**Total days**: {s.get('total_days', '?')}  ")
        lines.append(f"**Players**: {s.get('player_count', '?')}  ")
        lines.append("")

        # Game summary
        gs = s.get("game_summary", {})
        if gs:
            lines.append("## Game Summary")
            lines.append("")
            lines.append(f"- Good team avg score: {gs.get('good_team_avg', 0):.2f}")
            lines.append(f"- Wolf team avg score: {gs.get('wolf_team_avg', 0):.2f}")
            lines.append(f"- Total deaths: {gs.get('total_deaths', 0)}")
            lines.append(f"- Total exiles: {gs.get('total_exiles', 0)}")
            lines.append("")

        # Player scores
        players = s.get("player_scores", [])
        if players:
            lines.append("## Player Scores")
            lines.append("")
            lines.append(
                "| Seat | Role | Speech | Vote | Skill | Info | Coop | Overall |"
            )
            lines.append(
                "|------|------|--------|------|-------|------|------|---------|"
            )
            for p in sorted(players, key=lambda x: x.get("seat", 0)):
                lines.append(
                    f"| {p.get('seat', '?')} "
                    f"| {p.get('role', '?')} "
                    f"| {p.get('speech', 0):.2f} "
                    f"| {p.get('vote', 0):.2f} "
                    f"| {p.get('skill', 0):.2f} "
                    f"| {p.get('information', 0):.2f} "
                    f"| {p.get('cooperation', 0):.2f} "
                    f"| {p.get('overall', 0):.2f} |"
                )
            lines.append("")

        # Turning points
        tps = s.get("turning_points", [])
        if tps:
            lines.append("## Turning Points")
            lines.append("")
            for tp in tps:
                lines.append(
                    f"- **Day {tp.get('day', '?')}** ({tp.get('phase', '?')}): "
                    f"{tp.get('description', '')} "
                    f"[{tp.get('quality', '?')}]"
                )
                if tp.get("alternative"):
                    lines.append(f"  - Alternative: {tp['alternative']}")
            lines.append("")

        # Counterfactuals
        cfs = s.get("counterfactuals", [])
        if cfs:
            lines.append("## Counterfactual Analysis")
            lines.append("")
            for cf in cfs:
                lines.append(f"- **What if**: {cf.get('what_if', '')}")
                lines.append(f"  - **Likely outcome**: {cf.get('likely_outcome', '')}")
                lines.append(f"  - Confidence: {cf.get('confidence', 0):.0%}")
                lines.append("")

        # Timeline
        timeline = s.get("timeline", [])
        if timeline:
            lines.append("## Event Timeline")
            lines.append("")
            for entry in timeline:
                lines.append(
                    f"- Day {entry.get('day', '?')} "
                    f"({entry.get('phase', '?')}): "
                    f"{entry.get('event', '')}"
                )
            lines.append("")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Report generator
# ---------------------------------------------------------------------------


class ReportGenerator:
    """Generate structured game reports from evaluation and review data."""

    def generate(
        self,
        game_id: str,
        *,
        evaluation: Any,  # GameEvaluation
        reviews: list[Any],  # DecisionReview list
        counterfactuals: list[Any],  # Counterfactual list
        events: list[dict],
        player_roles: dict[int, str],
        winner: str,
        total_days: int,
    ) -> GameReport:
        """Build a structured ``GameReport``.

        Sections
        --------
        - **game_summary**: winner, days, key stats
        - **player_scores**: radar-chart data per player (5 dimensions)
        - **turning_points**: key moments with quality labels
        - **timeline**: major events chronologically
        - **counterfactuals**: what-if scenarios
        """
        summary: dict[str, Any] = {}

        # --- Game summary ---
        summary["winner"] = winner
        summary["total_days"] = total_days
        summary["player_count"] = len(player_roles)

        good_scores: list[float] = []
        wolf_scores: list[float] = []
        player_scores: list[dict[str, Any]] = []

        if evaluation is not None and hasattr(evaluation, "players"):
            for pe in evaluation.players:
                score_entry = {
                    "seat": pe.player_seat,
                    "role": pe.role,
                    "speech": pe.speech_score,
                    "vote": pe.vote_score,
                    "skill": pe.skill_score,
                    "information": pe.information_score,
                    "cooperation": pe.cooperation_score,
                    "overall": pe.overall_score,
                }
                player_scores.append(score_entry)

                if _is_werewolf(pe.role):
                    wolf_scores.append(pe.overall_score)
                else:
                    good_scores.append(pe.overall_score)

        summary["player_scores"] = player_scores
        summary["game_summary"] = {
            "good_team_avg": _safe_avg(good_scores),
            "wolf_team_avg": _safe_avg(wolf_scores),
            "total_deaths": sum(
                1 for e in events if e.get("event_type") == "death"
            ),
            "total_exiles": sum(
                1
                for e in events
                if e.get("event_type") == "death"
                and (e.get("payload", {}) or {}).get("cause") == "exile"
            ),
        }

        # --- Turning points ---
        turning_points: list[dict[str, Any]] = []
        for rev in reviews:
            tp_entry = {
                "day": rev.day,
                "phase": rev.phase,
                "seat": rev.player_seat,
                "action_type": rev.action_type,
                "quality": rev.quality,
                "description": rev.reason,
                "alternative": rev.alternative_action,
            }
            turning_points.append(tp_entry)

        # Sort by day then phase
        turning_points.sort(key=lambda x: (x.get("day", 0), x.get("phase", "")))
        summary["turning_points"] = turning_points

        # --- Counterfactuals ---
        cf_entries: list[dict[str, Any]] = []
        for cf in counterfactuals:
            cf_entries.append({
                "decision_id": cf.decision_id,
                "what_if": cf.what_if,
                "likely_outcome": cf.likely_outcome,
                "confidence": cf.confidence,
            })
        summary["counterfactuals"] = cf_entries

        # --- Timeline: major events chronologically ---
        timeline: list[dict[str, Any]] = []
        for e in events:
            event_type = e.get("event_type", "")
            entry = _timeline_entry(e, player_roles)
            if entry:
                timeline.append(entry)

        timeline.sort(key=lambda x: (x.get("day", 0), x.get("phase", "")))
        summary["timeline"] = timeline

        now = beijing_now_iso()
        return GameReport(
            id=str(uuid.uuid4()),
            game_id=game_id,
            summary=summary,
            created_at=now,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_avg(values: list[float]) -> float:
    if not values:
        return 0.0
    return round(sum(values) / len(values), 3)


def _timeline_entry(event: dict, player_roles: dict[int, str]) -> dict | None:
    """Convert a game event into a human-readable timeline entry.

    Returns ``None`` for events that are not significant enough.
    """
    event_type = event.get("event_type", "")
    day = event.get("day", 0)
    phase = event.get("phase", "")
    actor = event.get("actor")
    target = event.get("target")
    payload = event.get("payload", {}) or {}

    actor_role = player_roles.get(int(actor), "") if actor is not None else ""
    target_role = player_roles.get(int(target), "") if target is not None else ""

    if event_type == "death":
        cause = payload.get("cause", "unknown")
        return {
            "day": day,
            "phase": phase,
            "event": (
                f"P{target} ({target_role}) died "
                f"(cause: {cause})"
            ),
        }

    if event_type == "werewolf_result":
        return {
            "day": day,
            "phase": phase,
            "event": f"Wolves attacked P{target}",
        }

    if event_type == "seer_result":
        result = payload.get("result", "?")
        return {
            "day": day,
            "phase": phase,
            "event": f"Seer checked P{target}: {result}",
        }

    if event_type == "exile_result":
        return {
            "day": day,
            "phase": phase,
            "event": f"P{target} ({target_role}) was exiled by vote",
        }

    if event_type == "hunter_shot":
        return {
            "day": day,
            "phase": phase,
            "event": f"Hunter P{actor} shot P{target} ({target_role})",
        }

    if event_type == "witch_result":
        choice = payload.get("choice", "unknown")
        return {
            "day": day,
            "phase": phase,
            "event": f"Witch used {choice} on P{target}",
        }

    if event_type == "guard_result":
        return {
            "day": day,
            "phase": phase,
            "event": f"Guard protected P{target}",
        }

    if event_type == "white_wolf_explode":
        return {
            "day": day,
            "phase": phase,
            "event": f"White wolf king P{actor} exploded",
        }

    if event_type == "sheriff_elected":
        return {
            "day": day,
            "phase": phase,
            "event": f"P{target} ({target_role}) was elected sheriff",
        }

    if event_type == "game_end":
        return {
            "day": day,
            "phase": phase,
            "event": f"Game ended. Winner: {payload.get('winner', 'unknown')}",
        }

    # Skip minor / internal events
    return None
