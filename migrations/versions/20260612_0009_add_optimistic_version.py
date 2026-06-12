"""Add optimistic locking version column to evolution_runs.

Revision ID: 20260612_0009
Revises: 20260611_0008
Create Date: 2026-06-12
"""

from __future__ import annotations

from alembic import op

revision = "20260612_0009"
down_revision = "20260611_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE evolution.evolution_runs "
        "ADD COLUMN IF NOT EXISTS optimistic_version integer NOT NULL DEFAULT 1"
    )
    op.execute(
        "ALTER TABLE wolf.benchmark_leaderboard "
        "ADD COLUMN IF NOT EXISTS optimistic_version integer NOT NULL DEFAULT 1"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE evolution.evolution_runs "
        "DROP COLUMN IF EXISTS optimistic_version"
    )
    op.execute(
        "ALTER TABLE wolf.benchmark_leaderboard "
        "DROP COLUMN IF EXISTS optimistic_version"
    )
