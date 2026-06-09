"""Add benchmark saved views table."""

from __future__ import annotations

from alembic import op

revision = "20260610_0002"
down_revision = "20260608_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS wolf.benchmark_saved_views (
            view_key text PRIMARY KEY,
            name text NOT NULL,
            scope text NOT NULL,
            benchmark_id text,
            evaluation_set_id text,
            target_role text,
            view_config jsonb NOT NULL,
            created_at timestamptz NOT NULL,
            updated_at timestamptz NOT NULL
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_bench_view_scope_eval "
        "ON wolf.benchmark_saved_views(scope, evaluation_set_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_bench_view_benchmark "
        "ON wolf.benchmark_saved_views(benchmark_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS wolf.benchmark_saved_views")
