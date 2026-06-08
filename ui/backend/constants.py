"""Shared constants for the UI backend."""

ROLE_ORDER = (
    "villager",
    "werewolf",
    "white_wolf_king",
    "seer",
    "witch",
    "hunter",
    "guard",
)

LOG_SOURCE_LABELS = {
    "normal": "人机/玩家",
    "benchmark": "批量评测",
    "evolution": "自进化",
}

EVOLUTION_PHASE_LABELS = {
    "train": "训练对局",
    "battle_baseline": "基线对战",
    "battle_candidate": "候选对战",
}

BACKGROUND_ACTIVE_STATUSES = {
    "queued",
    "running",
    "training",
    "consolidating",
    "applying",
    "battling",
}

BACKGROUND_STABLE_STATUSES = {
    "reviewing",
    "promoted",
    "rejected",
    "failed",
    "completed",
    "cancelled",
    "interrupted",
}

MANUAL_STOP_REASON = "stopped"
