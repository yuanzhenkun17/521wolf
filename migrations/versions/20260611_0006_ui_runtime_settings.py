"""Add UI runtime settings table."""

from __future__ import annotations

from alembic import op

revision = "20260611_0006"
down_revision = "20260611_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS wolf.ui_runtime_settings (
            setting_key text PRIMARY KEY,
            value_json jsonb NOT NULL,
            updated_at timestamptz NOT NULL,
            updated_by text
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_ui_runtime_settings_updated
        ON wolf.ui_runtime_settings(updated_at)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS wolf.ui_runtime_settings")
