"""Battle database schema -- tables for game runtime data."""

from __future__ import annotations

BATTLE_SCHEMA = """
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

-- Evaluations
CREATE TABLE IF NOT EXISTS evaluations (
    id TEXT PRIMARY KEY,
    game_id TEXT NOT NULL REFERENCES games(id),
    player_seat INTEGER NOT NULL,
    role TEXT NOT NULL,
    speech_score REAL,
    vote_score REAL,
    skill_score REAL,
    information_score REAL,
    cooperation_score REAL,
    overall_score REAL,
    created_at TEXT NOT NULL
);

-- Decision reviews
CREATE TABLE IF NOT EXISTS decision_reviews (
    id TEXT PRIMARY KEY,
    game_id TEXT NOT NULL REFERENCES games(id),
    decision_id TEXT NOT NULL,
    player_seat INTEGER NOT NULL,
    day INTEGER NOT NULL,
    phase TEXT NOT NULL,
    action_type TEXT NOT NULL,
    quality TEXT NOT NULL,
    reason TEXT,
    alternative_action TEXT,
    created_at TEXT NOT NULL
);

-- Counterfactuals
CREATE TABLE IF NOT EXISTS counterfactuals (
    id TEXT PRIMARY KEY,
    game_id TEXT NOT NULL REFERENCES games(id),
    decision_id TEXT NOT NULL,
    what_if TEXT NOT NULL,
    likely_outcome TEXT,
    confidence REAL,
    created_at TEXT NOT NULL
);

-- Reports
CREATE TABLE IF NOT EXISTS reports (
    id TEXT PRIMARY KEY,
    game_id TEXT NOT NULL UNIQUE REFERENCES games(id),
    summary TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- Leaderboard
CREATE TABLE IF NOT EXISTS leaderboard (
    role TEXT NOT NULL,
    version_id TEXT NOT NULL,
    games_played INTEGER DEFAULT 0,
    wins INTEGER DEFAULT 0,
    win_rate REAL DEFAULT 0.0,
    avg_speech_score REAL DEFAULT 0.0,
    avg_vote_score REAL DEFAULT 0.0,
    avg_skill_score REAL DEFAULT 0.0,
    avg_information_score REAL DEFAULT 0.0,
    avg_cooperation_score REAL DEFAULT 0.0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (role, version_id)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_decisions_game ON decisions(game_id);
CREATE INDEX IF NOT EXISTS idx_decisions_role ON decisions(role);
CREATE INDEX IF NOT EXISTS idx_decisions_version ON decisions(version_id);
CREATE INDEX IF NOT EXISTS idx_decisions_action ON decisions(action_type);
CREATE INDEX IF NOT EXISTS idx_decisions_created ON decisions(created_at);
CREATE INDEX IF NOT EXISTS idx_players_game ON players(game_id);
CREATE INDEX IF NOT EXISTS idx_players_role ON players(role);
CREATE INDEX IF NOT EXISTS idx_ge_game ON game_events(game_id);
CREATE INDEX IF NOT EXISTS idx_ge_type ON game_events(event_type);
CREATE INDEX IF NOT EXISTS idx_ge_day ON game_events(game_id, day);
CREATE INDEX IF NOT EXISTS idx_evaluations_game ON evaluations(game_id);
CREATE INDEX IF NOT EXISTS idx_evaluations_role ON evaluations(role);
CREATE INDEX IF NOT EXISTS idx_decision_reviews_game ON decision_reviews(game_id);
CREATE INDEX IF NOT EXISTS idx_decision_reviews_decision ON decision_reviews(decision_id);
CREATE INDEX IF NOT EXISTS idx_counterfactuals_game ON counterfactuals(game_id);
CREATE INDEX IF NOT EXISTS idx_counterfactuals_decision ON counterfactuals(decision_id);
CREATE INDEX IF NOT EXISTS idx_leaderboard_role ON leaderboard(role);
CREATE INDEX IF NOT EXISTS idx_leaderboard_version ON leaderboard(version_id);
"""
