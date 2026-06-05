"""Registry database schema -- tables for role version tracking and skill storage."""

from __future__ import annotations

import sqlite3

REGISTRY_SCHEMA = """
-- Role versions (primary version tracking table)
CREATE TABLE IF NOT EXISTS role_versions (
    id TEXT NOT NULL,
    role TEXT NOT NULL,
    parent_id TEXT,
    source TEXT NOT NULL,
    run_id TEXT,
    skills TEXT NOT NULL,
    notes TEXT,
    status TEXT DEFAULT 'active',
    created_at TEXT NOT NULL,
    -- KnowledgePackage metadata (stored as JSON)
    patterns_json TEXT,
    metrics_json TEXT,
    provenance_json TEXT,
    PRIMARY KEY (id, role)
);

-- Role current baseline (fast lookup for current baseline per role)
CREATE TABLE IF NOT EXISTS role_current_baseline (
    role TEXT PRIMARY KEY,
    version_id TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Role baseline history (audit trail for baseline changes)
CREATE TABLE IF NOT EXISTS role_baseline_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role TEXT NOT NULL,
    version_id TEXT NOT NULL,
    previous_version_id TEXT,
    reason TEXT,
    created_at TEXT NOT NULL
);

-- Skill files (content of individual .md skill files per version)
CREATE TABLE IF NOT EXISTS skill_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    version_id TEXT NOT NULL,
    file_path TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(version_id, file_path)
);

-- Rejected proposals (per role, stored as JSON array)
CREATE TABLE IF NOT EXISTS rejected_proposals (
    role TEXT PRIMARY KEY,
    proposals_json TEXT NOT NULL
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_role_versions_role ON role_versions(role);
CREATE INDEX IF NOT EXISTS idx_role_versions_status ON role_versions(status);
CREATE INDEX IF NOT EXISTS idx_skill_files_version ON skill_files(version_id);
"""


def ensure_registry_schema(conn: sqlite3.Connection) -> None:
    """Create registry tables if they do not exist."""
    conn.executescript(REGISTRY_SCHEMA)
    conn.commit()
