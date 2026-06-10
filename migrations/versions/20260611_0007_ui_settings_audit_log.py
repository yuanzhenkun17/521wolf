"""Add UI settings audit log table."""

from __future__ import annotations

from alembic import op

revision = "20260611_0007"
down_revision = "20260611_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS wolf.ui_settings_audit_log (
            audit_id text PRIMARY KEY,
            action text NOT NULL,
            entity_kind text NOT NULL,
            entity_id text NOT NULL,
            status text NOT NULL,
            actor text NOT NULL,
            message text,
            details jsonb NOT NULL,
            created_at timestamptz NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_ui_settings_audit_created
        ON wolf.ui_settings_audit_log(created_at DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_ui_settings_audit_entity
        ON wolf.ui_settings_audit_log(entity_kind, entity_id, created_at DESC)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS wolf.ui_settings_audit_log")
