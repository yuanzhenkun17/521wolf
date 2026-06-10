"""Add UI task worker heartbeat table."""

from __future__ import annotations

from alembic import op

revision = "20260610_0004"
down_revision = "20260610_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS wolf.ui_task_workers (
            worker_id text PRIMARY KEY,
            status text NOT NULL,
            last_heartbeat_at timestamptz NOT NULL,
            lease_seconds integer NOT NULL,
            current_task_id text,
            metadata jsonb
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_ui_task_workers_heartbeat
        ON wolf.ui_task_workers(last_heartbeat_at)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS wolf.ui_task_workers")
