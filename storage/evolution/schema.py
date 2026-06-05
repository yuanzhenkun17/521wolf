"""Evolution database schema -- tables for learning and evolution data."""

from __future__ import annotations

EVOLUTION_SCHEMA = """
-- Evolution runs
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

-- Skill proposals
CREATE TABLE IF NOT EXISTS skill_proposals (
    id TEXT PRIMARY KEY,
    source_version_id TEXT,
    target_version_id TEXT,
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

-- Experience candidates
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
    PRIMARY KEY (game_id, candidate_id)
);

-- Patterns
CREATE TABLE IF NOT EXISTS patterns (
    pattern_id TEXT PRIMARY KEY,
    role TEXT NOT NULL,
    situation TEXT NOT NULL,
    recommendation TEXT NOT NULL,
    win_rate_with REAL DEFAULT 0.5,
    win_rate_without REAL DEFAULT 0.5,
    sample_size INTEGER DEFAULT 0,
    confidence REAL DEFAULT 0.1,
    alpha REAL DEFAULT 1.0,
    beta REAL DEFAULT 1.0,
    status TEXT DEFAULT 'candidate',
    source_games TEXT,
    version_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Rejected proposals
CREATE TABLE IF NOT EXISTS rejected_proposals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role TEXT NOT NULL,
    proposal_json TEXT NOT NULL,
    battle_score_delta REAL,
    battle_win_rate_delta REAL,
    created_at TEXT NOT NULL
);

-- Situational records
CREATE TABLE IF NOT EXISTS situational_records (
    id TEXT PRIMARY KEY,
    game_id TEXT NOT NULL,
    role TEXT NOT NULL,
    seat INTEGER NOT NULL,
    day INTEGER,
    phase TEXT,
    alive_players TEXT,
    key_events TEXT,
    outcome TEXT,
    created_at TEXT NOT NULL
);

-- Decision outcomes
CREATE TABLE IF NOT EXISTS decision_outcomes (
    decision_id TEXT PRIMARY KEY,
    game_id TEXT NOT NULL,
    player_seat INTEGER NOT NULL,
    role TEXT NOT NULL,
    action_type TEXT NOT NULL,
    day INTEGER NOT NULL,
    phase TEXT NOT NULL,
    quality TEXT,
    reason TEXT,
    created_at TEXT NOT NULL
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_evolution_runs_role ON evolution_runs(role);
CREATE INDEX IF NOT EXISTS idx_skill_proposals_source ON skill_proposals(source_version_id);
CREATE INDEX IF NOT EXISTS idx_exp_game ON experience_candidates(game_id);
CREATE INDEX IF NOT EXISTS idx_exp_role ON experience_candidates(role);
CREATE INDEX IF NOT EXISTS idx_exp_type ON experience_candidates(candidate_type);
CREATE INDEX IF NOT EXISTS idx_exp_created ON experience_candidates(created_at);
CREATE INDEX IF NOT EXISTS idx_patterns_role ON patterns(role);
CREATE INDEX IF NOT EXISTS idx_patterns_status ON patterns(status);
CREATE INDEX IF NOT EXISTS idx_rejected_role ON rejected_proposals(role);
CREATE INDEX IF NOT EXISTS idx_situational_game ON situational_records(game_id);
CREATE INDEX IF NOT EXISTS idx_situational_role ON situational_records(role);
CREATE INDEX IF NOT EXISTS idx_outcomes_game ON decision_outcomes(game_id);
CREATE INDEX IF NOT EXISTS idx_outcomes_role ON decision_outcomes(role);
CREATE INDEX IF NOT EXISTS idx_outcomes_decision ON decision_outcomes(decision_id);
"""
