"""Evolution database schema -- tables for learning and evolution data."""

from __future__ import annotations

import sqlite3

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

-- Role versions (moved to registry.db -- definition kept for migration only)
-- CREATE TABLE IF NOT EXISTS role_versions (
--     id TEXT PRIMARY KEY,
--     role TEXT NOT NULL,
--     parent_id TEXT REFERENCES role_versions(id),
--     source TEXT NOT NULL,
--     run_id TEXT,
--     skills TEXT NOT NULL,
--     notes TEXT,
--     status TEXT DEFAULT 'active',
--     created_at TEXT NOT NULL
-- );

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
    -- Phase 1/7: run policy columns
    run_type TEXT DEFAULT 'evolution_training',
    source_run_id TEXT,
    source_game_id TEXT,
    artifact_game_id TEXT,
    learning_eligible INTEGER DEFAULT 1,
    mode TEXT DEFAULT 'formal',
    applicable_phase TEXT,
    applicable_action TEXT,
    llm_rationale TEXT,
    validator_status TEXT,
    PRIMARY KEY (game_id, candidate_id)
);

-- Patterns (legacy, not written in Phase 1)
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
    phase TEXT,
    action_type TEXT,
    proposal_json TEXT NOT NULL,
    rejection_reason TEXT,
    rejection_scope TEXT,
    confidence TEXT DEFAULT 'low',
    battle_score_delta REAL,
    battle_win_rate_delta REAL,
    created_at TEXT NOT NULL
);

-- Situational records (legacy, not written in Phase 1)
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

-- Decision outcomes (legacy, not written in Phase 1)
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

-- Evolution rounds (Phase 7: round state machine)
CREATE TABLE IF NOT EXISTS evolution_rounds (
    round_id TEXT PRIMARY KEY,
    role TEXT NOT NULL,
    branch_id TEXT,
    parent_version_id TEXT,
    generation INTEGER DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'created',
    run_type TEXT DEFAULT 'evolution_training',
    learning_eligible INTEGER DEFAULT 1,
    mode TEXT DEFAULT 'formal',
    training_game_count INTEGER DEFAULT 0,
    config TEXT,
    learning_pipeline_version TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT
);

-- Candidate packages (Phase 7: A/B validation)
CREATE TABLE IF NOT EXISTS candidate_packages (
    package_id TEXT PRIMARY KEY,
    round_id TEXT NOT NULL,
    role TEXT NOT NULL,
    candidate_version_id TEXT,
    skill_package_hash TEXT,
    proposal_ids TEXT,
    status TEXT DEFAULT 'pending',
    ab_summary TEXT,
    created_at TEXT NOT NULL
);

-- Promotion decisions (Phase 7)
CREATE TABLE IF NOT EXISTS promotion_decisions (
    decision_id TEXT PRIMARY KEY,
    round_id TEXT NOT NULL,
    package_id TEXT NOT NULL,
    role TEXT NOT NULL,
    outcome TEXT NOT NULL,
    reason TEXT,
    metrics TEXT,
    seed_set_id TEXT,
    scoring_version TEXT,
    learning_pipeline_version TEXT,
    created_at TEXT NOT NULL
);

-- A/B comparison groups (Phase 7)
CREATE TABLE IF NOT EXISTS ab_comparison_groups (
    group_id TEXT PRIMARY KEY,
    round_id TEXT NOT NULL,
    role TEXT NOT NULL,
    baseline_run_id TEXT,
    candidate_run_id TEXT,
    game_count INTEGER DEFAULT 0,
    summary TEXT,
    created_at TEXT NOT NULL
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_evolution_runs_role ON evolution_runs(role);
CREATE INDEX IF NOT EXISTS idx_skill_proposals_source ON skill_proposals(source_version_id);
CREATE INDEX IF NOT EXISTS idx_exp_game ON experience_candidates(game_id);
CREATE INDEX IF NOT EXISTS idx_exp_role ON experience_candidates(role);
CREATE INDEX IF NOT EXISTS idx_exp_type ON experience_candidates(candidate_type);
CREATE INDEX IF NOT EXISTS idx_exp_created ON experience_candidates(created_at);
CREATE INDEX IF NOT EXISTS idx_exp_run_type ON experience_candidates(run_type);
CREATE INDEX IF NOT EXISTS idx_exp_learning ON experience_candidates(learning_eligible);
CREATE INDEX IF NOT EXISTS idx_patterns_role ON patterns(role);
CREATE INDEX IF NOT EXISTS idx_patterns_status ON patterns(status);
CREATE INDEX IF NOT EXISTS idx_rejected_role ON rejected_proposals(role);
CREATE INDEX IF NOT EXISTS idx_situational_game ON situational_records(game_id);
CREATE INDEX IF NOT EXISTS idx_situational_role ON situational_records(role);
CREATE INDEX IF NOT EXISTS idx_outcomes_game ON decision_outcomes(game_id);
CREATE INDEX IF NOT EXISTS idx_outcomes_role ON decision_outcomes(role);
CREATE INDEX IF NOT EXISTS idx_outcomes_decision ON decision_outcomes(decision_id);
CREATE INDEX IF NOT EXISTS idx_evo_rounds_role ON evolution_rounds(role);
CREATE INDEX IF NOT EXISTS idx_evo_rounds_status ON evolution_rounds(status);
CREATE INDEX IF NOT EXISTS idx_candidate_pkg_round ON candidate_packages(round_id);
CREATE INDEX IF NOT EXISTS idx_promo_round ON promotion_decisions(round_id);
CREATE INDEX IF NOT EXISTS idx_ab_group_round ON ab_comparison_groups(round_id);
"""


# Columns added to experience_candidates during Phase 1/7 refactor.
_EXP_NEW_COLUMNS = [
    ("run_type", "TEXT DEFAULT 'evolution_training'"),
    ("source_run_id", "TEXT"),
    ("source_game_id", "TEXT"),
    ("artifact_game_id", "TEXT"),
    ("learning_eligible", "INTEGER DEFAULT 1"),
    ("mode", "TEXT DEFAULT 'formal'"),
    ("applicable_phase", "TEXT"),
    ("applicable_action", "TEXT"),
    ("llm_rationale", "TEXT"),
    ("validator_status", "TEXT"),
]

_REJECTED_NEW_COLUMNS = [
    ("phase", "TEXT"),
    ("action_type", "TEXT"),
    ("rejection_reason", "TEXT"),
    ("rejection_scope", "TEXT"),
    ("confidence", "TEXT DEFAULT 'low'"),
]


def ensure_evolution_schema(conn: sqlite3.Connection) -> None:
    """Create evolution tables and migrate existing ones."""
    conn.executescript(EVOLUTION_SCHEMA)
    _ensure_exp_columns(conn)
    _ensure_rejected_columns(conn)


def _ensure_exp_columns(conn: sqlite3.Connection) -> None:
    existing = {row[1] for row in conn.execute("PRAGMA table_info(experience_candidates)")}
    for col, decl in _EXP_NEW_COLUMNS:
        if col not in existing:
            conn.execute(f"ALTER TABLE experience_candidates ADD COLUMN {col} {decl}")


def _ensure_rejected_columns(conn: sqlite3.Connection) -> None:
    existing = {row[1] for row in conn.execute("PRAGMA table_info(rejected_proposals)")}
    for col, decl in _REJECTED_NEW_COLUMNS:
        if col not in existing:
            conn.execute(f"ALTER TABLE rejected_proposals ADD COLUMN {col} {decl}")
