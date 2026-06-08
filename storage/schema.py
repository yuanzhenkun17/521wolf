"""Database schema and connection management."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from storage.shared.connection import connect_sqlite, record_schema_version

SCHEMA_VERSION = 1

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
    final_state TEXT,
    -- Run policy columns (Phase 1 refactor)
    run_type TEXT DEFAULT 'ordinary_game',
    mode TEXT DEFAULT 'dev',
    learning_eligible INTEGER DEFAULT 0,
    leaderboard_scope TEXT DEFAULT 'demo',
    promote_eligible INTEGER DEFAULT 0,
    source_run_id TEXT,
    comparison_group_id TEXT,
    comparison_type TEXT,
    model_id TEXT,
    model_config_hash TEXT,
    target_role TEXT,
    target_version_id TEXT,
    ruleset_version TEXT DEFAULT 'werewolf_12p_v1',
    seed_set_id TEXT,
    evaluation_set_id TEXT,
    paired_seed INTEGER DEFAULT 0,
    rankable INTEGER DEFAULT 0
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
    -- Run policy columns (Phase 1 refactor)
    role_version_id TEXT,
    skill_package_hash TEXT,
    model_id TEXT,
    model_config_hash TEXT,
    role_sample_status TEXT DEFAULT 'valid',
    role_sample_invalid_reason TEXT,
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
    public INTEGER DEFAULT 1,
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
    avg_speech_score REAL DEFAULT 0.0,
    avg_vote_score REAL DEFAULT 0.0,
    avg_skill_score REAL DEFAULT 0.0,
    avg_information_score REAL DEFAULT 0.0,
    avg_cooperation_score REAL DEFAULT 0.0,
    updated_at TEXT NOT NULL
);

-- Battle evaluation tables (merged from battle.db)
CREATE TABLE IF NOT EXISTS evaluations (
    id TEXT PRIMARY KEY,
    game_id TEXT NOT NULL REFERENCES games(id),
    player_seat INTEGER,
    role TEXT,
    -- Spec scoring dimensions (scoring_v1)
    speech_score REAL,
    vote_score REAL,
    skill_score REAL,
    logic_score REAL,
    team_score REAL,
    risk_penalty REAL DEFAULT 0.0,
    role_score REAL,
    score_completeness REAL DEFAULT 1.0,
    -- Legacy fields (kept for backward compat, not authoritative)
    information_score REAL,
    cooperation_score REAL,
    overall_score REAL,
    -- Metadata
    role_sample_status TEXT DEFAULT 'valid',
    role_sample_invalid_reason TEXT,
    ruleset_version TEXT DEFAULT 'werewolf_12p_v1',
    scoring_version TEXT DEFAULT 'scoring_v1',
    evaluator_config_hash TEXT DEFAULT 'rule_heuristic_v1',
    evaluation_status TEXT DEFAULT 'completed',
    review_status TEXT DEFAULT 'completed',
    report_status TEXT DEFAULT 'completed',
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS decision_reviews (
    id TEXT PRIMARY KEY,
    game_id TEXT NOT NULL REFERENCES games(id),
    decision_id TEXT,
    player_seat INTEGER,
    day INTEGER,
    phase TEXT,
    action_type TEXT,
    quality TEXT,
    reason TEXT,
    alternative_action TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS counterfactuals (
    id TEXT PRIMARY KEY,
    game_id TEXT NOT NULL REFERENCES games(id),
    decision_id TEXT,
    what_if TEXT,
    likely_outcome TEXT,
    confidence REAL,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS reports (
    id TEXT PRIMARY KEY,
    game_id TEXT NOT NULL UNIQUE REFERENCES games(id),
    summary TEXT,
    created_at TEXT
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_decisions_game ON decisions(game_id);
CREATE INDEX IF NOT EXISTS idx_decisions_role ON decisions(role);
CREATE INDEX IF NOT EXISTS idx_decisions_version ON decisions(version_id);
CREATE INDEX IF NOT EXISTS idx_decisions_action ON decisions(action_type);
CREATE INDEX IF NOT EXISTS idx_decisions_created ON decisions(created_at);
CREATE INDEX IF NOT EXISTS idx_players_game ON players(game_id);
CREATE INDEX IF NOT EXISTS idx_players_role ON players(role);
CREATE INDEX IF NOT EXISTS idx_leaderboard_role ON leaderboard(role);
CREATE INDEX IF NOT EXISTS idx_leaderboard_version ON leaderboard(version_id);
CREATE INDEX IF NOT EXISTS idx_ge_game ON game_events(game_id);
CREATE INDEX IF NOT EXISTS idx_ge_type ON game_events(event_type);
CREATE INDEX IF NOT EXISTS idx_ge_day ON game_events(game_id, day);

-- Battle evaluation indexes (merged from battle.db)
CREATE INDEX IF NOT EXISTS idx_eval_game ON evaluations(game_id);
CREATE INDEX IF NOT EXISTS idx_eval_role ON evaluations(role);
CREATE INDEX IF NOT EXISTS idx_dr_game ON decision_reviews(game_id);
CREATE INDEX IF NOT EXISTS idx_dr_decision ON decision_reviews(decision_id);
CREATE INDEX IF NOT EXISTS idx_cf_game ON counterfactuals(game_id);
CREATE INDEX IF NOT EXISTS idx_cf_decision ON counterfactuals(decision_id);

-- LLM structured judgments (Phase 4 spec)
CREATE TABLE IF NOT EXISTS llm_judgments (
    judgment_id TEXT PRIMARY KEY,
    game_id TEXT NOT NULL,
    player_id INTEGER,
    dimension TEXT NOT NULL,
    prompt_version TEXT,
    evaluator_config_hash TEXT,
    input_refs TEXT,
    raw_json TEXT,
    normalized_fields TEXT,
    validator_status TEXT DEFAULT 'valid',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_judgment_game ON llm_judgments(game_id);
CREATE INDEX IF NOT EXISTS idx_judgment_player ON llm_judgments(player_id);
CREATE INDEX IF NOT EXISTS idx_judgment_dimension ON llm_judgments(dimension);

-- New indexes for run policy columns
CREATE INDEX IF NOT EXISTS idx_games_run_type ON games(run_type);
CREATE INDEX IF NOT EXISTS idx_games_learning ON games(learning_eligible);
CREATE INDEX IF NOT EXISTS idx_games_leaderboard ON games(leaderboard_scope);

-- Seed sets (immutable)
CREATE TABLE IF NOT EXISTS seed_sets (
    seed_set_id TEXT PRIMARY KEY,
    purpose TEXT,
    seeds_json TEXT NOT NULL,
    ruleset_version TEXT DEFAULT 'werewolf_12p_v1',
    created_at TEXT NOT NULL,
    immutable INTEGER DEFAULT 1
);

-- Evaluation batches
CREATE TABLE IF NOT EXISTS evaluation_batches (
    id TEXT PRIMARY KEY,
    comparison_group_id TEXT,
    comparison_type TEXT,
    mode TEXT DEFAULT 'dev',
    model_id TEXT,
    model_config_hash TEXT,
    target_role TEXT,
    target_version_id TEXT,
    role_version_config TEXT,
    game_count INTEGER,
    evaluation_set_id TEXT,
    seed_set_id TEXT,
    max_days INTEGER DEFAULT 20,
    player_count INTEGER DEFAULT 12,
    ruleset_version TEXT DEFAULT 'werewolf_12p_v1',
    rankable INTEGER DEFAULT 0,
    rankable_reason TEXT,
    summary TEXT,
    started_at TEXT,
    finished_at TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_eval_batches_group ON evaluation_batches(comparison_group_id);
CREATE INDEX IF NOT EXISTS idx_eval_batches_type ON evaluation_batches(comparison_type);

-- Benchmark leaderboard
CREATE TABLE IF NOT EXISTS benchmark_leaderboard (
    id TEXT PRIMARY KEY,
    scope TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    model_id TEXT,
    model_config_hash TEXT,
    target_role TEXT,
    target_version_id TEXT,
    comparison_group_id TEXT,
    evaluation_set_id TEXT,
    seed_set_id TEXT,
    ruleset_version TEXT DEFAULT 'werewolf_12p_v1',
    scoring_version TEXT DEFAULT 'scoring_v1',
    evaluator_config_hash TEXT,
    games_played INTEGER DEFAULT 0,
    valid_game_rate REAL DEFAULT 0.0,
    strength_score REAL DEFAULT 0.0,
    avg_role_score REAL DEFAULT 0.0,
    by_role_category_scores TEXT,
    avg_speech_score REAL DEFAULT 0.0,
    avg_vote_score REAL DEFAULT 0.0,
    avg_skill_score REAL DEFAULT 0.0,
    avg_logic_score REAL DEFAULT 0.0,
    avg_team_score REAL DEFAULT 0.0,
    risk_penalty REAL DEFAULT 0.0,
    fallback_rate REAL DEFAULT 0.0,
    llm_error_rate REAL DEFAULT 0.0,
    policy_adjusted_rate REAL DEFAULT 0.0,
    good_side_win_rate REAL DEFAULT 0.0,
    wolf_side_win_rate REAL DEFAULT 0.0,
    target_side_win_rate REAL DEFAULT 0.0,
    rankable INTEGER DEFAULT 0,
    data_sufficient INTEGER DEFAULT 0,
    summary TEXT,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_bench_scope ON benchmark_leaderboard(scope);
CREATE INDEX IF NOT EXISTS idx_bench_subject ON benchmark_leaderboard(subject_id);
CREATE INDEX IF NOT EXISTS idx_bench_group ON benchmark_leaderboard(comparison_group_id);
"""


def get_connection(db_path: Path) -> sqlite3.Connection:
    """Create a SQLite connection with WAL mode and schema initialized."""
    conn = connect_sqlite(db_path)
    # Migrate existing tables first (adds new columns to old DBs)
    _ensure_game_columns(conn)
    _ensure_player_columns(conn)
    _ensure_evaluation_columns(conn)
    # Now run full schema (CREATE TABLE IF NOT EXISTS + indexes)
    conn.executescript(SCHEMA)
    record_schema_version(conn, component="wolf", version=SCHEMA_VERSION)
    conn.commit()
    return conn


# Columns added to games table during Phase 1 refactor.
# For existing DBs that already have the base schema, ALTER TABLE is needed.
_GAMES_NEW_COLUMNS = [
    ("run_type", "TEXT DEFAULT 'ordinary_game'"),
    ("mode", "TEXT DEFAULT 'dev'"),
    ("learning_eligible", "INTEGER DEFAULT 0"),
    ("leaderboard_scope", "TEXT DEFAULT 'demo'"),
    ("promote_eligible", "INTEGER DEFAULT 0"),
    ("source_run_id", "TEXT"),
    ("comparison_group_id", "TEXT"),
    ("comparison_type", "TEXT"),
    ("model_id", "TEXT"),
    ("model_config_hash", "TEXT"),
    ("target_role", "TEXT"),
    ("target_version_id", "TEXT"),
    ("ruleset_version", "TEXT DEFAULT 'werewolf_12p_v1'"),
    ("seed_set_id", "TEXT"),
    ("evaluation_set_id", "TEXT"),
    ("paired_seed", "INTEGER DEFAULT 0"),
    ("rankable", "INTEGER DEFAULT 0"),
]

_PLAYERS_NEW_COLUMNS = [
    ("role_version_id", "TEXT"),
    ("skill_package_hash", "TEXT"),
    ("model_id", "TEXT"),
    ("model_config_hash", "TEXT"),
    ("role_sample_status", "TEXT DEFAULT 'valid'"),
    ("role_sample_invalid_reason", "TEXT"),
]

_EVALUATIONS_NEW_COLUMNS = [
    ("logic_score", "REAL"),
    ("team_score", "REAL"),
    ("risk_penalty", "REAL DEFAULT 0.0"),
    ("role_score", "REAL"),
    ("score_completeness", "REAL DEFAULT 1.0"),
    ("role_sample_status", "TEXT DEFAULT 'valid'"),
    ("role_sample_invalid_reason", "TEXT"),
    ("ruleset_version", "TEXT DEFAULT 'werewolf_12p_v1'"),
    ("scoring_version", "TEXT DEFAULT 'scoring_v1'"),
    ("evaluator_config_hash", "TEXT DEFAULT 'rule_heuristic_v1'"),
    ("evaluation_status", "TEXT DEFAULT 'completed'"),
    ("review_status", "TEXT DEFAULT 'completed'"),
    ("report_status", "TEXT DEFAULT 'completed'"),
]


def _ensure_game_columns(conn: sqlite3.Connection) -> None:
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "games" not in tables:
        return
    existing = {row[1] for row in conn.execute("PRAGMA table_info(games)")}
    for col, decl in _GAMES_NEW_COLUMNS:
        if col not in existing:
            conn.execute(f"ALTER TABLE games ADD COLUMN {col} {decl}")


def _ensure_player_columns(conn: sqlite3.Connection) -> None:
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "players" not in tables:
        return
    existing = {row[1] for row in conn.execute("PRAGMA table_info(players)")}
    for col, decl in _PLAYERS_NEW_COLUMNS:
        if col not in existing:
            conn.execute(f"ALTER TABLE players ADD COLUMN {col} {decl}")


def _ensure_evaluation_columns(conn: sqlite3.Connection) -> None:
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "evaluations" not in tables:
        return
    existing = {row[1] for row in conn.execute("PRAGMA table_info(evaluations)")}
    for col, decl in _EVALUATIONS_NEW_COLUMNS:
        if col not in existing:
            conn.execute(f"ALTER TABLE evaluations ADD COLUMN {col} {decl}")
