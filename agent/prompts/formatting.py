"""Prompt formatting utilities for structured context blocks."""

from __future__ import annotations


def format_field_notes(field_notes: dict) -> str:
    """Format structured field notes into a compact prompt block."""
    parts = []

    gs = field_notes.get("game_state", {})
    if gs:
        alive = gs.get("alive_players", [])
        dead = gs.get("dead_players", [])
        parts.append(
            f"当前状态: 第{gs.get('day', '?')}天 {gs.get('phase', '?')}，"
            f"存活 {alive}，死亡 {dead}"
        )

    profiles = field_notes.get("player_profiles", {})
    if profiles:
        profile_lines = []
        for pid_str, info in sorted(profiles.items()):
            parts_list = []
            sc = info.get("speech_count", 0)
            if sc:
                parts_list.append(f"发言{sc}次")
            for vote in info.get("votes_cast", []):
                parts_list.append(f"投票给P{vote.get('target')}")
            received = info.get("votes_received", [])
            if received:
                parts_list.append(f"被{'、'.join(f'P{r}' for r in received)}投票")
            for a in info.get("attacked", []):
                parts_list.append(f"攻击过P{a}")
            for d in info.get("defended", []):
                parts_list.append(f"辩护过P{d}")
            for f in info.get("followed", []):
                parts_list.append(f"跟票P{f}")
            if parts_list:
                profile_lines.append(f"  - P{pid_str}: {'，'.join(parts_list)}")
        if profile_lines:
            parts.append("玩家画像:")
            parts.extend(profile_lines)

    patterns = field_notes.get("vote_patterns", [])
    if patterns:
        parts.append("票型模式:")
        for p in patterns:
            parts.append(f"  - {p}")

    events = field_notes.get("key_events", [])
    if events:
        parts.append("关键事件:")
        for e in events:
            parts.append(f"  - {e}")

    return "\n".join(parts) if parts else ""
