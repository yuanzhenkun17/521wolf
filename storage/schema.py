"""Database schema and connection management."""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
-- Game domain
CREATE TABLE IF NOT EXISTS games (
    id TEXT PRIMARY KEY,
    seed INTEGER NOT NULL,
    config TEXT,
    winner TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    total_rounds INTEGER DEFAULT 0,
    public_events TEXT,
    final_state TEXT
);

CREATE TABLE IF NOT EXISTS players (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id TEXT NOT NULL REFERENCES games(id),
    seat INTEGER NOT NULL,
    role TEXT NOT NULL,
    team TEXT NOT NULL,
    alive INTEGER DEFAULT 1,
    killed_day INTEGER,
    killed_cause TEXT,
    UNIQUE(game_id, seat)
);

-- Decision domain
CREATE TABLE IF NOT EXISTS decisions (
    id TEXT PRIMARY KEY,
    game_id TEXT NOT NULL,
    player_id INTEGER,
    seat INTEGER NOT NULL,
    role TEXT NOT NULL,
    day INTEGER NOT NULL,
    phase TEXT NOT NULL,
    action_type TEXT NOT NULL,
    candidates TEXT,
    observation_summary TEXT,
    memory_context TEXT,
    selected_skills TEXT,
    prompt_messages TEXT,
    raw_output TEXT,
    parsed_decision TEXT,
    final_response TEXT,
    selected_target INTEGER,
    selected_choice TEXT,
    public_text TEXT,
    private_reasoning TEXT,
    confidence REAL,
    alternatives TEXT,
    rejected_reasons TEXT,
    memory_refs TEXT,
    memory_summary TEXT,
    source TEXT,
    policy_adjustments TEXT,
    errors TEXT,
    version_id TEXT,
    latency_ms REAL,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    created_at TEXT NOT NULL
);

-- Evidence learning domain
CREATE TABLE IF NOT EXISTS experience_candidates (
    game_id TEXT NOT NULL,
    candidate_id TEXT NOT NULL,
    role TEXT,
    faction TEXT,
    candidate_type TEXT,
    topic TEXT,
    sample_source TEXT,
    evidence_decision_ids TEXT,
    scenario TEXT,
    conditions TEXT,
    recommendation TEXT,
    anti_pattern TEXT,
    risk_boundaries TEXT,
    counter_conditions TEXT,
    supporting_evidence TEXT,
    opposing_evidence TEXT,
    confidence TEXT,
    validation_need TEXT,
    misleading_risk TEXT,
    raw_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (game_id, candidate_id),
    FOREIGN KEY (game_id) REFERENCES games(id)
);

-- Evolution domain
CREATE TABLE IF NOT EXISTS role_versions (
    id TEXT PRIMARY KEY,
    role TEXT NOT NULL,
    parent_id TEXT REFERENCES role_versions(id),
    source TEXT NOT NULL,
    run_id TEXT,
    skills TEXT NOT NULL,
    notes TEXT,
    status TEXT DEFAULT 'active',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS skill_proposals (
    id TEXT PRIMARY KEY,
    source_version_id TEXT,
    target_version_id TEXT REFERENCES role_versions(id),
    target_file TEXT NOT NULL,
    action_type TEXT NOT NULL,
    content TEXT NOT NULL,
    rationale TEXT,
    confidence REAL,
    risk TEXT,
    expected_metric TEXT,
    expected_direction TEXT,
    evidence TEXT,
    status TEXT DEFAULT 'proposed',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS evolution_runs (
    id TEXT PRIMARY KEY,
    role TEXT NOT NULL,
    parent_hash TEXT,
    status TEXT NOT NULL,
    training_games INTEGER DEFAULT 0,
    battle_games INTEGER DEFAULT 0,
    config TEXT,
    candidate_hash TEXT,
    battle_result TEXT,
    errors TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT
);

-- Engine event domain
CREATE TABLE IF NOT EXISTS game_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id TEXT NOT NULL,
    idx INTEGER NOT NULL,
    day INTEGER NOT NULL,
    phase TEXT NOT NULL,
    event_type TEXT NOT NULL,
    message TEXT,
    level TEXT,
    visibility TEXT,
    actor INTEGER,
    target INTEGER,
    payload TEXT,
    created_at TEXT
);

-- Leaderboard
CREATE TABLE IF NOT EXISTS leaderboard (
    version_id TEXT NOT NULL,
    role TEXT NOT NULL,
    games_played INTEGER DEFAULT 0,
    wins INTEGER DEFAULT 0,
    losses INTEGER DEFAULT 0,
    win_rate REAL DEFAULT 0.0,
    avg_survival_rounds REAL DEFAULT 0.0,
    target_side_win_rate REAL DEFAULT 0.0,
    win_rate_ci_low REAL DEFAULT 0.0,
    win_rate_ci_high REAL DEFAULT 0.0,
    scores TEXT,
    is_baseline INTEGER DEFAULT 0,
    data_sufficient INTEGER DEFAULT 0,
    updated_at TEXT NOT NULL
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_decisions_game ON decisions(game_id);
CREATE INDEX IF NOT EXISTS idx_decisions_role ON decisions(role);
CREATE INDEX IF NOT EXISTS idx_decisions_version ON decisions(version_id);
CREATE INDEX IF NOT EXISTS idx_decisions_action ON decisions(action_type);
CREATE INDEX IF NOT EXISTS idx_decisions_created ON decisions(created_at);
CREATE INDEX IF NOT EXISTS idx_players_game ON players(game_id);
CREATE INDEX IF NOT EXISTS idx_players_role ON players(role);
CREATE INDEX IF NOT EXISTS idx_role_versions_role ON role_versions(role);
CREATE INDEX IF NOT EXISTS idx_leaderboard_role ON leaderboard(role);
CREATE INDEX IF NOT EXISTS idx_leaderboard_version ON leaderboard(version_id);
CREATE INDEX IF NOT EXISTS idx_evolution_runs_role ON evolution_runs(role);
CREATE INDEX IF NOT EXISTS idx_skill_proposals_source ON skill_proposals(source_version_id);
CREATE INDEX IF NOT EXISTS idx_ge_game ON game_events(game_id);
CREATE INDEX IF NOT EXISTS idx_ge_type ON game_events(event_type);
CREATE INDEX IF NOT EXISTS idx_ge_day ON game_events(game_id, day);
CREATE INDEX IF NOT EXISTS idx_exp_game ON experience_candidates(game_id);
CREATE INDEX IF NOT EXISTS idx_exp_role ON experience_candidates(role);
CREATE INDEX IF NOT EXISTS idx_exp_type ON experience_candidates(candidate_type);
CREATE INDEX IF NOT EXISTS idx_exp_created ON experience_candidates(created_at);
"""


def get_connection(db_path: Path) -> sqlite3.Connection:
    """Create a SQLite connection with WAL mode and schema initialized."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn
