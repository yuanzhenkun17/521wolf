"""Add encrypted UI model profile settings table."""

from __future__ import annotations

from alembic import op

revision = "20260611_0005"
down_revision = "20260610_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS wolf.ui_model_profiles (
            profile_id text PRIMARY KEY,
            name text NOT NULL,
            provider text NOT NULL,
            base_url text NOT NULL,
            model text NOT NULL,
            api_key_ciphertext text,
            api_key_kid text,
            api_key_masked text,
            temperature double precision,
            timeout_seconds integer,
            max_retries integer,
            enabled boolean NOT NULL DEFAULT true,
            default_scopes jsonb NOT NULL,
            capabilities jsonb NOT NULL,
            metadata jsonb,
            created_at timestamptz NOT NULL,
            updated_at timestamptz NOT NULL,
            last_tested_at timestamptz,
            last_test_status text NOT NULL DEFAULT 'untested',
            last_test_error text
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_ui_model_profiles_enabled
        ON wolf.ui_model_profiles(enabled, updated_at)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_ui_model_profiles_provider_model
        ON wolf.ui_model_profiles(provider, model)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS wolf.ui_model_profiles")
