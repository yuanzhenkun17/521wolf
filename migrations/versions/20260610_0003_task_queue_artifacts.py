"""Add UI task queue and artifact index tables."""

from __future__ import annotations

from alembic import op

revision = "20260610_0003"
down_revision = "20260610_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS wolf.ui_task_queue (
            task_id text PRIMARY KEY,
            kind text NOT NULL,
            status text NOT NULL,
            priority integer NOT NULL DEFAULT 100,
            payload jsonb NOT NULL,
            result jsonb,
            error jsonb,
            progress jsonb,
            attempt integer NOT NULL DEFAULT 0,
            max_attempts integer NOT NULL DEFAULT 1,
            lease_owner text,
            lease_expires_at timestamptz,
            queued_at timestamptz NOT NULL,
            started_at timestamptz,
            updated_at timestamptz NOT NULL,
            finished_at timestamptz,
            cancel_requested boolean NOT NULL DEFAULT false,
            idempotency_key text,
            parent_task_id text,
            source text,
            metadata jsonb
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_ui_task_queue_status_priority
        ON wolf.ui_task_queue(status, priority, queued_at)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_ui_task_queue_lease
        ON wolf.ui_task_queue(lease_expires_at)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_ui_task_queue_kind
        ON wolf.ui_task_queue(kind, updated_at)
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_ui_task_queue_idempotency
        ON wolf.ui_task_queue(idempotency_key)
        WHERE idempotency_key IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS wolf.ui_task_artifacts (
            artifact_id text PRIMARY KEY,
            task_id text NOT NULL,
            artifact_type text NOT NULL,
            name text NOT NULL,
            relative_path text NOT NULL,
            content_type text,
            size_bytes bigint,
            sha256 text,
            created_at timestamptz NOT NULL,
            metadata jsonb
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_ui_task_artifacts_task
        ON wolf.ui_task_artifacts(task_id, created_at)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_ui_task_artifacts_type
        ON wolf.ui_task_artifacts(artifact_type, created_at)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_ui_task_artifacts_sha256
        ON wolf.ui_task_artifacts(sha256)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS wolf.ui_task_artifacts")
    op.execute("DROP TABLE IF EXISTS wolf.ui_task_queue")
